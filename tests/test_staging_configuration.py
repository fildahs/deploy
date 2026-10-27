import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

from scripts.assert_staging import assert_staging

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'tests/fixtures/pre-staging'
SAFE_ENV = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/tmp'),
            'SECRET_KEY': 'placeholder-secret', 'QDRANT_API_KEY': 'placeholder-key',
            'POSTGRES_PASSWORD': 'placeholder-password'}


def run(*args, env=None):
    return subprocess.check_output(args, cwd=ROOT, env=env, text=True, stderr=subprocess.PIPE)


def config(*files, staging=False):
    return json.loads(run('docker', 'compose', '--project-directory', str(ROOT), '-p', 'staging' if staging else 'deploy',
                          '--env-file', str(ROOT / 'staging.env.sample') if staging else '/dev/null',
                          *[arg for file in files for arg in ('-f', str(file))], 'config', '--format', 'json', env=SAFE_ENV))


class ComposeCompatibilityTests(unittest.TestCase):
    def test_production_is_identical_to_committed_pre_task_config(self):
        self.assertEqual(config(BASELINE / 'compose.yml'), config(ROOT / 'compose.yml'))

    def test_staging_is_isolated_and_every_service_is_limited(self):
        data = config(ROOT / 'compose.yml', ROOT / 'compose.staging.yml', staging=True)
        assert_staging(data)
        self.assertTrue(any(mount['source'].endswith('/Caddyfile.staging') for mount in data['services']['caddy']['volumes']))
        for key, changed in [('ports', ['80:80']), ('networks', {'foreign-network': None}), ('mem_limit', 0)]:
            bad = copy.deepcopy(data)
            bad['services']['api'][key] = changed
            with self.subTest(key=key), self.assertRaises(AssertionError):
                assert_staging(bad)
        for collection in ('volumes', 'networks'):
            bad = copy.deepcopy(data)
            next(iter(bad[collection].values()))['external'] = True
            with self.subTest(collection=collection), self.assertRaises(AssertionError):
                assert_staging(bad)

    def test_caddy_production_adapts_to_identical_json(self):
        def adapt(file):
            return json.loads(run('docker', 'run', '--rm', '--network', 'none',
                                  '-e', 'CADDY_ACME_EMAIL=placeholder@example.invalid',
                                  '-v', f'{file}:/etc/caddy/Caddyfile:ro', 'caddy:2.8-alpine',
                                  'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile'))
        digest = hashlib.sha256(json.dumps(adapt(ROOT / 'Caddyfile'), sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, (BASELINE / 'Caddyfile.sha256').read_text().strip())

    def test_staging_proxy_has_exactly_seven_hosts(self):
        env = config(ROOT / 'compose.yml', ROOT / 'compose.staging.yml', staging=True)['services']['caddy']['environment']
        args = ['docker', 'run', '--rm', '--network', 'none',
                '-v', f'{ROOT / "Caddyfile.staging"}:/etc/caddy/Caddyfile:ro']
        for key, value in env.items():
            args.extend(['-e', f'{key}={value}'])
        data = json.loads(run(*args, 'caddy:2.8-alpine', 'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile'))
        hosts = {host for server in data['apps']['http']['servers'].values()
                 for route in server.get('routes', []) for match in route.get('match', [])
                 for host in match.get('host', [])}
        self.assertEqual(hosts, {f'fsandcube-{name}.fildah.com' for name in
                                ('www', 'auth', 'api', 'console', 'care', 'index', 'business')})

    def test_production_proxy_starts_without_upstream_containers(self):
        name = 'fildah-proxy-start-' + uuid.uuid4().hex[:10]
        run('docker', 'run', '-d', '--name', name, '--network', 'none',
            '-e', 'CADDY_ACME_EMAIL=placeholder@example.invalid',
            '-v', f'{ROOT / "Caddyfile"}:/etc/caddy/Caddyfile:ro', 'caddy:2.8-alpine')
        try:
            for attempt in range(30):
                try:
                    config_data = json.loads(run('docker', 'exec', name, 'wget', '-qO-', 'http://127.0.0.1:2019/config/'))
                    self.assertIn('http', config_data['apps'])
                    break
                except subprocess.CalledProcessError:
                    if attempt == 29:
                        self.fail('Proxy failed to start: ' + run('docker', 'logs', name))
                    time.sleep(0.2)
        finally:
            run('docker', 'rm', '-f', '-v', name)

    def test_env_diff_never_prints_values(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target.env'
            sample = Path(directory) / 'sample.env'
            target.write_text('export KEPT="SENTINEL-PRIVATE-VALUE"\n')
            sample.write_text('KEPT=placeholder\nMISSING=placeholder\n')
            result = run('python3', str(ROOT / 'scripts/env-names-diff'), str(target), '--sample', str(sample))
            self.assertEqual(result, 'MISSING\n')


class ProxyHeaderTests(unittest.TestCase):
    def test_tunnel_https_and_real_client_ip_survive_staging_caddy(self):
        suffix = uuid.uuid4().hex[:10]
        network, caddy, upstream = (f'fildah-header-{suffix}-{name}' for name in ('net', 'caddy', 'echo'))
        containers = []
        run('docker', 'network', 'create', '--internal', network)
        try:
            subnet = json.loads(run('docker', 'network', 'inspect', network))[0]['IPAM']['Config'][0]['Subnet']
            with tempfile.TemporaryDirectory() as directory:
                echo = Path(directory) / 'echo.conf'
                echo.write_text('server { listen 8000; location / { default_type application/json; return 200 \'{"scheme":"$http_x_forwarded_proto","client":"$http_x_real_ip"}\'; } }')
                run('docker', 'run', '-d', '--name', upstream, '--network', network, '--network-alias', 'api',
                    '-v', f'{echo}:/etc/nginx/conf.d/default.conf:ro', 'nginx:1.27-alpine')
                containers.append(upstream)
                args = ['docker', 'run', '-d', '--name', caddy, '--network', network, '--network-alias', 'caddy',
                        '-v', f'{ROOT / "Caddyfile.staging"}:/etc/caddy/Caddyfile:ro']
                env = {'API_HOST': 'http://staging-api.test', 'AUTH_HOST': 'http://auth.test',
                       'FILDAH_HOSTS': 'http://www.test', 'INDEX_HOST': 'http://index.test',
                       'CARE_HOST': 'http://care.test', 'CONSOLE_HOST': 'http://console.test', 'BUSINESS_HOST': 'http://business.test',
                       'CADDY_ACME_EMAIL': 'placeholder@example.invalid', 'CADDY_TRUSTED_PROXIES': subnet,
                       'STAGING_PROXY_HEADERS': 'header_up X-Forwarded-Proto {http.request.header.X-Forwarded-Proto}'}
                for key, value in env.items():
                    args.extend(['-e', f'{key}={value}'])
                run(*args, 'caddy:2.8-alpine')
                containers.append(caddy)
                for attempt in range(30):
                    try:
                        result = json.loads(run('docker', 'exec', upstream, 'wget', '-qO-',
                            '--header=Host: staging-api.test', '--header=Cf-Connecting-Ip: 203.0.113.77',
                            '--header=X-Forwarded-Proto: https', 'http://caddy/'))
                        break
                    except subprocess.CalledProcessError:
                        if attempt == 29:
                            self.fail('Disposable staging proxy did not become ready: ' + run('docker', 'logs', caddy))
                        time.sleep(0.2)
                self.assertEqual(result, {'scheme': 'https', 'client': '203.0.113.77'})
        finally:
            for container in reversed(containers):
                run('docker', 'rm', '-f', '-v', container)
            run('docker', 'network', 'rm', network)

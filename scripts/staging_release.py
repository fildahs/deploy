#!/usr/bin/env python3
"""Local staging gates, reproducible image publication and digest-pinned release.

No command connects to the VPS or loads runtime environment files. Publishing
is an explicit operator step after owner approval; `plan` has no network calls.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('api', 'auth-web', 'care-web', 'business-web', 'index-web', 'fildah-web', 'deploy')
IMAGES = {
    'FILDAH_API_IMAGE': ('api', 'fildah-api', 'app'),
    'FILDAH_WORKER_IMAGE': ('api', 'fildah-api-worker', 'worker'),
    'AUTH_WEB_IMAGE': ('auth-web', 'auth-web', None),
    'CARE_WEB_IMAGE': ('care-web', 'care-web', None),
    'BUSINESS_WEB_IMAGE': ('business-web', 'business-web', None),
    'INDEX_WEB_IMAGE': ('index-web', 'index-web', None),
    'FILDAH_WEB_IMAGE': ('fildah-web', 'fildah-web', None),
}
SHA_KEYS = dict(zip(SOURCES, ('API_SHA', 'AUTH_SHA', 'CARE_SHA', 'BUSINESS_SHA', 'INDEX_SHA', 'FILDAH_SHA', 'DEPLOY_SHA')))
URLS = {name: f'https://fsandcube-{host}.fildah.com' for name, host in {
    'VITE_API_BASE_URL': 'api', 'VITE_AUTH_BASE_URL': 'auth',
    'VITE_ACCOUNT_BASE_URL': 'www', 'VITE_MARKETING_BASE_URL': 'www',
    'VITE_CARE_URL': 'care', 'VITE_BUSINESS_URL': 'business',
    'VITE_INDEX_URL': 'index', 'VITE_SITE_URL': 'index',
}.items()}
BUILD_ARGS = {
    'auth-web': ('VITE_API_BASE_URL', 'VITE_ACCOUNT_BASE_URL', 'VITE_CARE_URL', 'VITE_BUSINESS_URL', 'VITE_INDEX_URL'),
    'care-web': ('VITE_API_BASE_URL', 'VITE_AUTH_BASE_URL', 'VITE_ACCOUNT_BASE_URL', 'VITE_MARKETING_BASE_URL'),
    'business-web': ('VITE_API_BASE_URL', 'VITE_AUTH_BASE_URL'),
    'index-web': ('VITE_API_BASE_URL', 'VITE_AUTH_BASE_URL', 'VITE_BUSINESS_URL', 'VITE_MARKETING_BASE_URL', 'VITE_SITE_URL'),
    'fildah-web': ('VITE_API_BASE_URL', 'VITE_AUTH_BASE_URL', 'VITE_CARE_URL'),
}


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def select(root=ROOT, require_pushed=False):
    result = {}
    for repo in SOURCES:
        path = root / repo
        if run(['git', 'branch', '--show-current'], cwd=path) != 'staging':
            raise ValueError(f'{repo}: checkout must be staging')
        if run(['git', 'status', '--porcelain'], cwd=path):
            raise ValueError(f'{repo}: commit or resolve working-tree changes first')
        sha = run(['git', 'rev-parse', 'HEAD'], cwd=path)
        # A fresh fetch is required by the runbook before the final gate. This
        # also refuses unpublished commits using the local remote tracking ref.
        if require_pushed and sha != run(['git', 'rev-parse', 'origin/staging'], cwd=path):
            raise ValueError(f'{repo}: selected commit must match origin/staging')
        result[repo] = sha
    return result


def fingerprint(root=ROOT):
    return hashlib.sha256((root / 'Makefile').read_bytes()).hexdigest()


def commands(repo):
    if repo == 'api':
        python = str(ROOT / 'api/venv/bin/python')
        wrapper = str(ROOT / 'deploy/scripts/staging_api_test.py')
        return [['make', 'check'], ['make', 'makemigrations', 'MIGRATE_ARGS=--check --dry-run'],
                ['make', 'test', f'PYTHON={python} {wrapper}'],
                ['make', 'test', f'PYTHON={python} {wrapper} --normal-hasher',
                 'TESTS=apps.identity.tests.test_google_security apps.identity.tests.test_accounts apps.identity.tests.test_mobile_auth apps.identity.tests.test_registration_flow']]
    if repo == 'deploy':
        return [['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-v']]
    result = [['npm', 'run', 'lint']]
    if repo != 'fildah-web':
        result.append(['npm', 'run', 'typecheck'])
    result.extend([['npm', 'test'], ['npm', 'run', 'build']])
    if repo in ('care-web', 'index-web'):
        result.extend([['npm', 'run', 'api:check'], ['npm', 'run', 'budget']])
    return result


def gate(directory):
    sources = select()
    make_sha = fingerprint()
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / 'gates.json'
    receipt.unlink(missing_ok=True)  # A failed repeat must not retain success.
    evidence = {}
    env = {**os.environ, **URLS, 'UNDER_CONSTRUCTION': 'false'}
    for repo in SOURCES:
        path = directory / f'{repo}.log'
        print(f'Checking {repo}; log: {path}', flush=True)
        with path.open('w') as log:
            for command in commands(repo):
                log.write('$ ' + ' '.join(command) + '\n')
                log.flush()
                subprocess.run(command, cwd=ROOT if repo == 'api' else ROOT / repo,
                               env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        evidence[repo] = hashlib.sha256(path.read_bytes()).hexdigest()
    if select() != sources or fingerprint() != make_sha:
        raise ValueError('Sources changed during the gate; rerun against the final commits')
    receipt.write_text(json.dumps({'sources': sources, 'makefile_sha256': make_sha,
                                   'build_urls': URLS, 'logs': evidence}, indent=2) + '\n')
    print(f'Local release gates passed: {receipt}')


def require_receipt(directory, sources):
    receipt = json.loads((directory / 'gates.json').read_text())
    if receipt['sources'] != sources or receipt['makefile_sha256'] != fingerprint() or receipt['build_urls'] != URLS:
        raise ValueError('Gate receipt does not match selected commits, Makefile and build URLs')
    for repo in SOURCES:
        if hashlib.sha256((directory / f'{repo}.log').read_bytes()).hexdigest() != receipt['logs'][repo]:
            raise ValueError(f'{repo}: gate log changed since verification')


def build_commands(sources, context):
    for variable, (repo, package, target) in IMAGES.items():
        tag = f'ghcr.io/fildahs/{package}:staging-{sources[repo]}'
        args = ['docker', 'buildx', 'build', '--platform', 'linux/amd64', '--push',
                '--tag', tag, '--label', f'org.opencontainers.image.revision={sources[repo]}',
                '--build-arg', f'APP_BUILD_SHA={sources[repo]}']
        if target:
            args.extend(['--target', target])
        for name in BUILD_ARGS.get(repo, ()):
            args.extend(['--build-arg', f'{name}={URLS[name]}'])
        if repo == 'care-web':
            args.extend(['--build-arg', 'UNDER_CONSTRUCTION=false'])
        if repo in ('auth-web', 'index-web'):
            # BuildKit passes the value directly; never print it or use ARG.
            args.extend(['--secret', 'id=ui_token,env=UI_BUILD_TOKEN'])
        args.append(str(context / repo))
        yield variable, tag, args


def publish(directory):
    sources = select(require_pushed=True)
    require_receipt(directory, sources)
    if not os.environ.get('UI_BUILD_TOKEN'):
        raise ValueError('Set UI_BUILD_TOKEN for private @fildah/ui dependency access (BuildKit secret)')
    (directory / 'staging.release').unlink(missing_ok=True)
    release = {SHA_KEYS[repo]: sha for repo, sha in sources.items()}
    # Export only committed files; ignored .env and installed deps cannot enter
    # an image context even if a Dockerignore rule is absent.
    with tempfile.TemporaryDirectory(prefix='fildah-staging-') as temp:
        context = Path(temp)
        for repo in SOURCES:
            dest = context / repo
            dest.mkdir()
            archive = context / f'{repo}.tar'
            subprocess.run(['git', 'archive', '-o', str(archive), sources[repo]], cwd=ROOT / repo, check=True)
            with tarfile.open(archive) as source:
                source.extractall(dest, filter='data')
        for variable, tag, args in build_commands(sources, context):
            print(f'Building and publishing {tag}', flush=True)
            metadata = context / 'metadata.json'
            subprocess.run(args[:-1] + ['--metadata-file', str(metadata), args[-1]], check=True)
            digest = json.loads(metadata.read_text())['containerimage.digest']
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                raise ValueError('Registry returned an invalid digest')
            # Inspect by digest, not the mutable tag, before writing the release.
            pinned = tag + '@' + digest
            subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', pinned], check=True, stdout=subprocess.DEVNULL)
            release[variable] = pinned
        if select(require_pushed=True) != sources or fingerprint() != json.loads((directory / 'gates.json').read_text())['makefile_sha256']:
            raise ValueError('Sources changed during publication; no release file written')
        bundle = directory / f'deploy-{sources["deploy"]}.tar'
        # Include only runtime/operator code; no secrets, generated files or .git.
        subprocess.run(['git', 'archive', '-o', str(bundle), sources['deploy'], 'compose.yml',
                        'compose.staging.yml', 'Caddyfile.staging', 'scripts'], cwd=ROOT / 'deploy', check=True)
        release['CONFIG_SHA256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (directory / 'staging.release').write_text(''.join(f'{key}={value}\n' for key, value in release.items()))
    print(f'Release prepared in {directory}; SSH rollout remains a separate approved step.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'gate', 'publish'))
    parser.add_argument('--output', type=Path, default=ROOT / '.local/staging-test-1/release')
    args = parser.parse_args()
    directory = args.output.resolve()
    if args.action == 'gate':
        gate(directory)
    elif args.action == 'publish':
        publish(directory)
    else:
        sources = select()
        print(json.dumps({'sources': sources, 'build_urls': URLS, 'commands':
                         [args for _, _, args in build_commands(sources, Path('<committed-export>'))]}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        # Do not echo subprocess environments or provider values.
        raise SystemExit('Local staging operation failed: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__)) from None

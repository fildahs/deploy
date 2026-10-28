import hashlib
import io
import tarfile
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import staging_release as release
from scripts.validate_staging_release import validate

ROOT = Path(__file__).resolve().parents[1]


class LocalStagingReleaseTests(unittest.TestCase):
    def test_images_have_staging_destinations_and_distinct_care_package(self):
        selected = {repo: 'a' * 40 for repo in release.SOURCES}
        builds = list(release.build_commands(selected, Path('/export')))
        self.assertEqual(len(builds), 7)
        for variable, tag, args in builds:
            self.assertTrue(tag.startswith('fildah-staging/') and tag.endswith(':current'))
            self.assertIn('--load', args)
            self.assertNotIn('--push', args)
            self.assertIn('linux/amd64', args)
            self.assertNotIn('CF_ACCESS_CLIENT_SECRET', ' '.join(args))
        care = next(args for name, _, args in builds if name == 'CARE_WEB_IMAGE')
        self.assertIn('fildah-staging/care-web:current', care)
        self.assertIn('UNDER_CONSTRUCTION=false', care)
        for value in release.URLS.values():
            self.assertTrue(value.startswith('https://fsandcube-'))

    def test_gate_receipt_rejects_changed_sources_makefile_urls_or_logs(self):
        sources = {repo: 'a' * 40 for repo in release.SOURCES}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            logs = {}
            for repo in sources:
                (directory / f'{repo}.log').write_text('passed')
                logs[repo] = hashlib.sha256(b'passed').hexdigest()
            data = {'sources': sources, 'makefile_sha256': 'make-hash', 'build_urls': release.URLS, 'logs': logs}
            receipt = directory / 'gates.json'
            receipt.write_text(json.dumps(data))
            with patch.object(release, 'fingerprint', return_value='make-hash'):
                release.require_receipt(directory, sources)
                with self.assertRaises(ValueError):
                    release.require_receipt(directory, {**sources, 'api': 'b' * 40})
                receipt.write_text(json.dumps({**data, 'build_urls': {}}))
                with self.assertRaises(ValueError):
                    release.require_receipt(directory, sources)
                receipt.write_text(json.dumps(data))
                (directory / 'api.log').write_text('tampered')
                with self.assertRaises(ValueError):
                    release.require_receipt(directory, sources)
            with patch.object(release, 'fingerprint', return_value='changed'), self.assertRaises(ValueError):
                release.require_receipt(directory, sources)

    def test_checkout_selection_refuses_dirty_wrong_branch_and_unpushed_sources(self):
        for answers in [('main',), ('staging', ' M runtime.py'), ('staging', '', 'a'*40, 'b'*40)]:
            with self.subTest(answers=answers), patch.object(release, 'run', side_effect=answers), self.assertRaises(ValueError):
                release.select(Path('/workspace'), require_pushed=True)

    def test_failed_gate_removes_old_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            receipt = directory / 'gates.json'
            receipt.write_text('old success')
            with patch.object(release, 'select', return_value={repo: 'a'*40 for repo in release.SOURCES}), patch.object(release, 'fingerprint', return_value='hash'), patch.object(release.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'test')):
                with self.assertRaises(subprocess.CalledProcessError):
                    release.gate(directory)
            self.assertFalse(receipt.exists())

    def test_repo_checkpoint_reuses_only_identical_inputs_and_unchanged_log(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            checkpoint, log = directory / 'gate.json', directory / 'gate.log'
            log.write_text('passed')
            inputs = {'source': 'a'*40, 'commands': [['test']], 'runner_sha256': 'original'}
            release.record_gate(checkpoint, inputs, log)
            self.assertTrue(release.reusable(checkpoint, inputs, log))
            for key, value in [('source', 'b'*40), ('commands', [['different']]), ('runner_sha256', 'changed')]:
                with self.subTest(key=key):
                    self.assertFalse(release.reusable(checkpoint, {**inputs, key: value}, log))
            log.write_text('modified')
            self.assertFalse(release.reusable(checkpoint, inputs, log))

    def test_staging_ssh_script_refuses_other_directories_before_docker(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/rollout-staging'), '/no/bundle', '/no/release'], cwd='/tmp', capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Wrong staging directory', result.stderr)

    def test_source_workflows_publish_only_main_and_old_staging_path_is_cut(self):
        self.assertFalse((ROOT / '.github/workflows/deploy-staging.yml').exists())
        self.assertFalse((ROOT / 'scripts/require_staging_ci.py').exists())
        if not (ROOT.parent / 'api/.github/workflows/ci.yml').is_file():
            self.skipTest('Cross-repo workflow audit requires shared workspace')
        for repo in release.SOURCES:
            workflow = (ROOT.parent / repo / '.github/workflows/ci.yml').read_text()
            with self.subTest(repo=repo):
                self.assertNotIn("github.ref == 'refs/heads/staging'", workflow)
                self.assertIn("if: github.ref == 'refs/heads/main'", workflow)
                self.assertIn('  push:\n    branches:\n      - main', workflow)

    def test_production_rollout_retains_ci_gate(self):
        workflow = (ROOT / '.github/workflows/deploy-production.yml').read_text()
        self.assertIn('python3 scripts/require_release_ci.py', workflow)
        self.assertIn('  workflow_dispatch:', workflow)
        self.assertNotIn('  push:', workflow)

    def test_production_rollout_targets_canonical_paths(self):
        workflow = (ROOT / '.github/workflows/deploy-production.yml').read_text()
        self.assertIn('/srv/fildah/production', workflow)
        self.assertIn('/srv/fildah/backups/production', workflow)
        self.assertNotIn('/srv/fildah/deploy', workflow)


class ReleaseValidationTests(unittest.TestCase):
    def artifact(self, directory, extra=None):
        bundle, manifest = directory / 'config.tar', directory / 'release'
        with tarfile.open(bundle, 'w') as archive:
            for name in ('compose.yml', 'compose.staging.yml', 'Caddyfile.staging', 'scripts/assert_staging.py', 'scripts/rollout-staging', 'scripts/validate_staging_release.py'):
                member = tarfile.TarInfo(name)
                member.size = 1
                archive.addfile(member, io.BytesIO(b'x'))
            if extra:
                archive.addfile(extra)
        data = {key: 'a'*40 for key in release.SHA_KEYS.values()}
        for variable, (_, package, _) in release.IMAGES.items():
            data[variable] = f'fildah-staging/{package}:current'
            data[variable + '_ID'] = 'sha256:' + 'b'*64
        data['CONFIG_SHA256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        manifest.write_text(''.join(f'{key}={value}\n' for key, value in data.items()))
        return bundle, manifest

    def test_accepts_local_images_and_matching_config(self):
        with tempfile.TemporaryDirectory() as temp:
            validate(*self.artifact(Path(temp)))

    def test_refuses_foreign_images_invalid_ids_and_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self.artifact(Path(temp))
            valid = manifest.read_text()
            changes = [valid.replace('fildah-staging/', 'ghcr.io/fildahs/', 1), valid.replace(':current', ':main', 1), valid.replace('sha256:'+'b'*64, 'invalid', 1), valid+'API_SHA='+'a'*40+'\n', valid.replace('CONFIG_SHA256=', 'UNKNOWN=')]
            for content in changes:
                manifest.write_text(content)
                with self.subTest(content=content[:20]), self.assertRaises(SystemExit):
                    validate(bundle, manifest)

    def test_loaded_image_checks_require_exact_id_and_source_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = self.artifact(Path(temp))
            info = {'Id': 'sha256:'+'b'*64, 'Config': {'Labels': {'org.opencontainers.image.revision': 'a'*40}}}
            with patch('scripts.validate_staging_release.subprocess.check_output', return_value=json.dumps([info])):
                validate(bundle, manifest, check_images=True)
            for changed in [{**info, 'Id': 'sha256:'+'c'*64}, {**info, 'Config': {'Labels': {'org.opencontainers.image.revision': 'c'*40}}}]:
                with self.subTest(changed=changed), patch('scripts.validate_staging_release.subprocess.check_output', return_value=json.dumps([changed])), self.assertRaises(SystemExit):
                    validate(bundle, manifest, check_images=True)

    def test_refuses_changed_archive_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            bundle, manifest = self.artifact(directory)
            bundle.write_bytes(bundle.read_bytes()+b'tampered')
            with self.assertRaises(SystemExit):
                validate(bundle, manifest)
            for name in ('../.env', '/srv/fildah/production/.env', '.env'):
                member = tarfile.TarInfo(name)
                with self.subTest(name=name), self.assertRaises(SystemExit):
                    validate(*self.artifact(directory, member))
            member = tarfile.TarInfo('scripts/link')
            member.type = tarfile.SYMTYPE
            member.linkname = '/srv/fildah/production/.env'
            with self.assertRaises(SystemExit):
                validate(*self.artifact(directory, member))

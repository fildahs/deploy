import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts.require_release_ci import require_successful_ci
from scripts.require_staging_ci import manifest, require_jobs, SERVICES

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


class StagingReleaseTests(unittest.TestCase):
    def env(self):
        return {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/staging',
                'DEPLOY_SHA': SHA, 'CHECKED_OUT_SHA': SHA, **{f'{key}_SHA': SHA for key in SERVICES}}

    def test_manifest_has_only_exact_staging_images(self):
        release = manifest(self.env())
        images = [value for name, value in release.items() if name.endswith('_IMAGE')]
        self.assertEqual(len(images), 7)
        self.assertTrue(all(value.endswith(':staging-' + SHA) for value in images))
        self.assertIn('/care-web:', release['CARE_WEB_IMAGE'])

    def test_wrong_ref_event_checkout_and_mutable_inputs_are_refused(self):
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/main'),
                           ('CHECKED_OUT_SHA', 'b' * 40), ('DEPLOY_SHA', 'staging'), ('API_SHA', SHA[:7])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                manifest({**self.env(), key: value})
        for key in SERVICES:
            with self.subTest(key=key), self.assertRaises(ValueError):
                manifest({**self.env(), f'{key}_SHA': ''})

    def test_ci_checks_exact_staging_branch_and_never_accepts_main_success(self):
        def run(branch):
            return {'id': 1, 'head_sha': SHA, 'head_branch': branch, 'head_repository': {'full_name': 'fildahs/api'},
                    'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success', 'run_number': 1}
        for branch in ('main', 'staging'):
            fetch = Mock(return_value=io.BytesIO(json.dumps({'workflow_runs': [run(branch)]}).encode()))
            if branch == 'main':
                with self.assertRaises(ValueError):
                    require_successful_ci('fildahs/api', SHA, 'dummy', fetch, branch='staging')
            else:
                require_successful_ci('fildahs/api', SHA, 'dummy', fetch, branch='staging')
            self.assertIn('branch=staging', fetch.call_args.args[0].full_url)

    def test_check_success_without_successful_publish_job_is_refused(self):
        def fetch(jobs):
            return Mock(return_value=io.BytesIO(json.dumps({'jobs': jobs}).encode()))
        checks = {'name': 'Backend', 'status': 'completed', 'conclusion': 'success'}
        publisher = {'name': 'Publish API Image', 'status': 'completed', 'conclusion': 'success'}
        for jobs in [[checks], [checks, {**publisher, 'conclusion': 'skipped'}],
                     [checks, {**publisher, 'status': 'in_progress'}]]:
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                require_jobs('fildahs/api', {'id': 1, 'run_attempt': 2}, 'dummy', fetch(jobs), ('Backend', 'Publish API Image'))
        request = fetch([checks, publisher])
        require_jobs('fildahs/api', {'id': 1, 'run_attempt': 2}, 'dummy', request, ('Backend', 'Publish API Image'))
        self.assertIn('/attempts/2/jobs', request.call_args.args[0].full_url)

    def test_staging_rollout_cannot_bypass_gate_or_operate_on_production(self):
        workflow = (ROOT / '.github/workflows/deploy-staging.yml').read_text()
        trigger = workflow.split('on:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertIn('  workflow_dispatch:', trigger)
        self.assertNotIn('  push:', trigger)
        self.assertNotIn('repository_dispatch:', trigger)
        self.assertLess(workflow.index('python3 scripts/require_staging_ci.py'), workflow.index('Configure SSH'))
        for expected in ['environment: staging', 'group: deploy-staging', 'cancel-in-progress: false',
                         'test "$(pwd -P)" = /srv/fildah/staging',
                         'docker compose -p staging -f compose.yml -f compose.staging.yml',
                         'scripts/assert_staging.py', '.release.previous', 'pg_dump', 'migrate --noinput',
                         'sync_platform_settings', 'docker compose -p deploy ps', 'production-containers.before',
                         '--exclude=\'.env\'']:
            self.assertIn(expected, workflow)
        self.assertNotIn('--delete', workflow)
        self.assertNotIn('pg_restore', workflow)

    def test_source_workflows_keep_staging_manual_and_use_staging_environment(self):
        if not (ROOT.parent / 'api/.github/workflows/ci.yml').is_file():
            self.skipTest('Cross-repo source workflow audit runs in the shared workspace.')
        for repo in ['api', 'auth-web', 'care-web', 'index-web', 'fildah-web', 'business-web']:
            workflow = (ROOT.parent / repo / '.github/workflows/ci.yml').read_text()
            with self.subTest(repo=repo):
                self.assertIn('publish_images:', workflow)
                self.assertIn('default: false', workflow)
                self.assertIn("github.ref == 'refs/heads/staging'", workflow)
                self.assertIn("&& 'staging' || ''", workflow)
                self.assertNotIn('pull_request:', workflow)
                self.assertIn('  push:\n    branches:\n      - main', workflow)
                self.assertTrue('staging-{0}' in workflow or 'staging-${{ github.sha }}' in workflow)

    def test_production_rollout_remains_manual(self):
        workflow = (ROOT / '.github/workflows/deploy-production.yml').read_text()
        trigger = workflow.split('on:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertIn('  workflow_dispatch:', trigger)
        self.assertNotIn('  push:', trigger)

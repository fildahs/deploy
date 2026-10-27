import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from scripts.require_release_ci import release_target, require_successful_ci


SHA = "a" * 40
OTHER_SHA = "b" * 40
REPO = "fildahs/api"


class ReleaseTargetTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": OTHER_SHA,
            "DEPLOY_APPROVED": "true",
            "SERVICE": "api",
            "IMAGE_TAG": SHA,
        }

    def test_approved_immutable_service_release(self):
        self.assertEqual(release_target(self.env), (REPO, SHA))

    def test_automatic_events_wrong_branch_and_missing_approval_are_blocked(self):
        for key, value in [
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_EVENT_NAME", "repository_dispatch"),
            ("GITHUB_REF", "refs/heads/staging"),
            ("DEPLOY_APPROVED", "false"),
            ("DEPLOY_APPROVED", ""),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                release_target({**self.env, key: value})

    def test_mutable_tags_and_mismatched_audit_inputs_are_blocked(self):
        for change in [
            {"IMAGE_TAG": "main"}, {"IMAGE_TAG": SHA[:7]}, {"IMAGE_TAG": ""},
            {"COMMIT_SHA": OTHER_SHA}, {"SOURCE_REPO": "fildahs/auth-web"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                release_target({**self.env, **change})

    def test_unknown_and_bulk_services_cannot_bypass_gate(self):
        for service in ["all", "business-web", "index-web", "unknown", ""]:
            with self.subTest(service=service), self.assertRaises(ValueError):
                release_target({**self.env, "SERVICE": service})

    def test_caddy_and_preflight_gate_the_deploy_revision(self):
        for service in ["caddy", "preflight"]:
            env = {**self.env, "SERVICE": service, "IMAGE_TAG": ""}
            self.assertEqual(release_target(env), ("fildahs/deploy", OTHER_SHA))
            with self.assertRaises(ValueError):
                release_target({**env, "COMMIT_SHA": SHA})


class ReleaseCITests(unittest.TestCase):
    def run_data(self, **overrides):
        return {
            "head_sha": SHA, "head_branch": "main", "event": "push",
            "head_repository": {"full_name": REPO},
            "status": "completed", "conclusion": "success",
            "run_number": 1, "run_attempt": 1, **overrides,
        }

    def check(self, runs):
        fetch = Mock(return_value=io.BytesIO(json.dumps({"workflow_runs": runs}).encode()))
        require_successful_ci(REPO, SHA, "test-token", fetch)
        request = fetch.call_args.args[0]
        self.assertIn("/actions/workflows/ci.yml/runs?", request.full_url)
        self.assertIn(f"head_sha={SHA}", request.full_url)
        self.assertIn("branch=main", request.full_url)

    def test_successful_exact_commit_is_accepted_for_push_or_manual_ci(self):
        for event in ["push", "workflow_dispatch"]:
            with self.subTest(event=event):
                self.check([self.run_data(event=event)])

    def test_missing_failed_pending_cancelled_and_skipped_ci_are_blocked(self):
        cases = [[], [self.run_data(conclusion="failure")],
                 [self.run_data(status="in_progress", conclusion=None)],
                 [self.run_data(conclusion="cancelled")],
                 [self.run_data(conclusion="skipped")]]
        for runs in cases:
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                self.check(runs)

    def test_other_commit_branch_fork_or_event_cannot_authorize_release(self):
        for change in [
            {"head_sha": OTHER_SHA}, {"head_branch": "staging"},
            {"head_repository": {"full_name": "someone/api"}},
            {"event": "pull_request"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check([self.run_data(**change)])

    def test_newer_failure_or_rerun_blocks_older_success(self):
        for newest in [
            self.run_data(run_number=2, conclusion="failure"),
            self.run_data(run_attempt=2, status="queued", conclusion=None),
        ]:
            with self.subTest(newest=newest), self.assertRaises(ValueError):
                self.check([self.run_data(), newest])

    def test_newer_success_allows_fixed_run(self):
        self.check([self.run_data(conclusion="failure"), self.run_data(run_number=2)])

    def test_github_access_failure_is_not_treated_as_success(self):
        fetch = Mock(side_effect=HTTPError("https://api.github.com", 403, "Forbidden", {}, None))
        with self.assertRaises(HTTPError):
            require_successful_ci(REPO, SHA, "test-token", fetch)


if __name__ == "__main__":
    unittest.main()

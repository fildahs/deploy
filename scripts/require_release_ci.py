"""Fail closed before SSH unless this approved release has successful main CI."""

import json
import os
import re
import urllib.parse
import urllib.request


SERVICE_REPOS = {
    "api": "fildahs/api",
    "auth-web": "fildahs/auth-web",
    "fildah-web": "fildahs/fildah-web",
    "index-web": "fildahs/index-web",
    "rxchat-web": "fildahs/care-web",
}


def release_target(env):
    if (
        env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("DEPLOY_APPROVED") != "true"
    ):
        raise ValueError("Run manually on main and explicitly confirm the production operation.")
    service = env.get("SERVICE")
    if service in {"caddy", "preflight"}:
        if env.get("IMAGE_TAG") or env.get("SOURCE_REPO") or env.get("COMMIT_SHA"):
            raise ValueError("Caddy/preflight use the deploy workflow commit; leave release inputs empty.")
        return "fildahs/deploy", env["GITHUB_SHA"]
    if service not in SERVICE_REPOS:
        raise ValueError("Choose one supported service; bulk 'all' deployments are disabled.")
    repo = SERVICE_REPOS[service]
    sha = env.get("IMAGE_TAG", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("image_tag must be the full immutable 40-character release commit SHA.")
    if env.get("SOURCE_REPO") not in {None, "", repo}:
        raise ValueError("source_repo does not match the selected service.")
    if env.get("COMMIT_SHA") not in {None, "", sha}:
        raise ValueError("commit_sha must match image_tag.")
    return repo, sha


def require_successful_ci(repo, sha, token, fetch, *, branch="main"):
    query = urllib.parse.urlencode({"head_sha": sha, "branch": branch, "per_page": 100})
    url = f"https://api.github.com/repos/{repo}/actions/workflows/ci.yml/runs?{query}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with fetch(request, timeout=30) as response:
        runs = json.load(response)["workflow_runs"]
    # Do not use an older success to bypass a newer failure or unfinished run.
    runs = [run for run in runs if (
        run.get("head_sha") == sha
        and run.get("head_branch") == branch
        and run.get("event") in {"push", "workflow_dispatch"}
        and run.get("head_repository", {}).get("full_name") == repo
    )]
    latest = max(runs, key=lambda run: (run["run_number"], run.get("run_attempt", 1)), default=None)
    if not latest or latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError(f"Successful CI is required for {repo}@{sha}; run CI and wait for it to pass.")
    return latest


def main():
    repo, sha = release_target(os.environ)
    token = os.environ.get("CI_READ_TOKEN", "").strip()
    if not token:
        raise ValueError("A token with Actions read access to the release repository is required.")
    # Gate deployment configuration as well as the application being released.
    targets = {("fildahs/deploy", os.environ["GITHUB_SHA"]), (repo, sha)}
    for target_repo, target_sha in sorted(targets):
        require_successful_ci(target_repo, target_sha, token, urllib.request.urlopen)
        print(f"CI passed: {target_repo}@{target_sha}")
    if os.environ["SERVICE"] in SERVICE_REPOS:
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            output.write(f"SOURCE_REPO={repo}\nCOMMIT_SHA={sha}\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"Deployment blocked: {exc}") from None

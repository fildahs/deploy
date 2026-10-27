"""Verify every selected staging commit and published image before SSH."""

import json
import os
import re
import subprocess
import urllib.request

if __package__:
    from .require_release_ci import require_successful_ci
else:
    from require_release_ci import require_successful_ci

SERVICES = {
    "API": ("api", ["fildah-api", "fildah-api-worker"], "Backend", "Publish API Image"),
    "AUTH": ("auth-web", ["auth-web"], "Fildah Auth Frontend", "Publish Fildah Auth Web Image"),
    "CARE": ("care-web", ["care-web"], "Care Frontend", "Publish Care Web Image"),
    "BUSINESS": ("business-web", ["business-web"], "frontend", "Publish Business staging image"),
    "INDEX": ("index-web", ["index-web"], "Fildah Index Frontend", "Publish Fildah Index Web Image"),
    "FILDAH": ("fildah-web", ["fildah-web"], "Fildah Frontend", "Publish Fildah Web Image"),
}
IMAGE_VARIABLES = {
    "fildah-api": "FILDAH_API_IMAGE", "fildah-api-worker": "FILDAH_WORKER_IMAGE",
    "auth-web": "AUTH_WEB_IMAGE", "care-web": "CARE_WEB_IMAGE", "business-web": "BUSINESS_WEB_IMAGE",
    "index-web": "INDEX_WEB_IMAGE", "fildah-web": "FILDAH_WEB_IMAGE",
}


def full_sha(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value or ""):
        raise ValueError("Every selected commit must be a full 40-character SHA.")
    return value


def manifest(env):
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or env.get("GITHUB_REF") != "refs/heads/staging":
        raise ValueError("Staging rollout must be manually dispatched on staging.")
    deploy_sha = full_sha(env.get("DEPLOY_SHA"))
    if env.get("CHECKED_OUT_SHA") != deploy_sha:
        raise ValueError("The checked-out deployment configuration must match DEPLOY_SHA.")
    result = {"DEPLOY_SHA": deploy_sha}
    for key, (_repo, packages, _checks, _publish) in SERVICES.items():
        sha = full_sha(env.get(f"{key}_SHA"))
        result[f"{key}_SHA"] = sha
        for package in packages:
            result[IMAGE_VARIABLES[package]] = f"ghcr.io/fildahs/{package}:staging-{sha}"
    return result


def require_jobs(repo, run, token, fetch, expected):
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run['id']}/attempts/{run.get('run_attempt', 1)}/jobs?per_page=100"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"})
    with fetch(request, timeout=30) as response:
        data = json.load(response)
    jobs = data["jobs"]
    if data.get("total_count", len(jobs)) > len(jobs):
        raise ValueError("Cannot verify all CI jobs from this response.")
    for name in expected:
        matching = [job for job in jobs if job.get("name") == name]
        if len(matching) != 1 or matching[0].get("conclusion") != "success" or matching[0].get("status") != "completed":
            raise ValueError(f"Required job did not succeed: {repo}: {name}")


def main():
    release = manifest(os.environ)
    token = os.environ.get("CI_READ_TOKEN", "").strip()
    if not token:
        raise ValueError("Actions read access to every source repository is required.")
    require_successful_ci("fildahs/deploy", release["DEPLOY_SHA"], token, urllib.request.urlopen, branch="staging")
    for key, (repo, packages, checks, publish) in SERVICES.items():
        run = require_successful_ci(f"fildahs/{repo}", release[f"{key}_SHA"], token, urllib.request.urlopen, branch="staging")
        require_jobs(f"fildahs/{repo}", run, token, urllib.request.urlopen, (checks, publish))
        for package in packages:
            subprocess.run(["docker", "buildx", "imagetools", "inspect", release[IMAGE_VARIABLES[package]]],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open("staging.release", "w", encoding="utf-8") as output:
        output.writelines(f"{key}={value}\n" for key, value in release.items())
    print("Exact staging CI, publish jobs and all seven immutable images verified.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError):
        raise SystemExit("Staging rollout blocked: commit, CI job, registry image or authorization verification failed.") from None

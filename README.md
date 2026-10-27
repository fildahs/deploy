# This folder contains the configuration needed to run the Fildah stack (`api`, `fildah-web`, and `care-web`) on your own Virtual Private Server (VPS).

Source documents and other Django media use the persistent `django_media`
volume by default. To move media to S3 or Cloudflare R2, copy the
`MEDIA_STORAGE_BACKEND` and `MEDIA_S3_*` settings from `.env.example` into the
host-managed `.env`. Never commit the real credentials.

## CI and deployment approval

Staging is verified and built locally: from the workspace root use
`make staging-plan`, `make staging-gate`, then the owner-approved
`make staging-build`. Images are loaded locally and streamed to the VPS with
`docker save | ssh docker load`; rollout is manual over approved
SSH. Source/deploy CI jobs run only on `main`; staging uses no Actions gate.
See [the staging runbook](docs/staging.md) for receipts, runtime setup,
data backups, image-ID verification and direct transfer.

When production deployment is ready and approved:

1. Run the source repository's **CI** workflow manually on `main`, enabling
   **publish_images**. This runs checks first, then builds and publishes
   images tagged with that exact commit SHA. Leave this option off for checks
   alone. Staging uses its separate local-build/direct-transfer procedure.
2. Wait for successful CI on both the application release and the selected
   deploy-repository `main` commit. If needed, run deploy **CI** manually.
3. In this repository choose **Actions → Deploy Production → Run workflow**,
   select `main`, choose one service, enter its full 40-character commit SHA
   as `image_tag`, and enable **confirm_deploy**. `source_repo` and `commit_sha`
   may be omitted; the gate derives them from the service and image SHA.
   For `caddy` or `preflight`, leave all three release fields empty.

A chat instruction explicitly approving CI, images and deployment authorizes
the agent to perform those manual steps. Asking for CI alone never authorizes
image publication or deployment. GitHub's manual confirmation is approval for
that operation; any configured `production` environment reviewers still apply.

The deployment workflow has no push, repository-dispatch or CI-completion
trigger. Before SSH, it requires manual approval, the `main` branch and a
successful `CI` workflow for the exact deploy-configuration and application
commits. Newer failed or unfinished CI blocks an older success. Mutable image
tags and bulk `all` deployments are rejected; deploy each service by SHA.

Set `DEPLOY_REPO_DISPATCH_TOKEN` in this repository to a token with **Actions:
read** access to the application repositories and this repository (the name
is retained for compatibility; deployments no longer dispatch automatically).
The built-in token can read this repository's CI but cannot normally read
private application repositories. Missing permissions block deployment.

Roll out the deploy-repository workflow change to `main` **before** merging
the application changes, so the production receiver stops accepting old
automatic dispatches first. Merging requires the owner's approval; this task
does not itself approve a merge or deployment. Manual workflow controls in
GitHub require the workflow to exist on the repository's default branch.

## Isolated staging

[Staging runbook](docs/staging.md): bootstrap, manual exact-SHA release,
rollback, separately approved database restore, and production folder-move requirements before rollout.

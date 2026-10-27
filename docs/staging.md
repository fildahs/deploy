# Fildah staging: local builds and manual rollout

Staging uses `/srv/fildah/staging`, Compose project `staging`, backup root
`/srv/fildah/backups/staging`, seven `fsandcube-*` hosts and the
`fildah-staging` Cloudflare Tunnel. It publishes no host ports. Production
keeps project `deploy`; independent RxChat keeps project `rxchat`.
Neither stack is deployed or moved by this procedure.

The owner's 2026-10-27 decision replaces staging Actions with local gates,
local builds, GHCR publication and an owner-approved SSH rollout. Production
Actions and its exact-SHA CI requirement remain. The old staging deployment
workflow and Actions gate have been removed. A manual CI dispatch on staging
skips source/deploy jobs; staging pushes never run CI.

## Prepare and review locally

1. Work on `staging` in each of the seven repositories. Finish and commit the
   release changes. Refresh remotes with `git fetch origin staging` in each
   repository. Keep the shared workspace Makefile with the release record.
2. From the workspace root run `make staging-plan`. It lists all full source
   SHAs, seven image builds and public staging build URLs without loading
   runtime env files or contacting the VPS. Each repository must be clean.
3. Run `make staging-gate`. It runs the full API suite against Docker Postgres
   through the workspace Makefile, Django checks and migration drift check;
   frontend lint/types/tests/builds, Care/Index contracts and budgets; and
   the Docker-backed deploy suite. Django creates a fresh test database and
   replays migrations without `--keepdb`. A process-local wrapper gives the
   broad suite cheap fixture password hashes, followed by Google/account/mobile/
   registration tests with normal hashers. It requires local PostgreSQL on
   127.0.0.1:5433 and uses separate fresh release/auth test databases; runtime
   application settings remain unchanged. Frontend builds use explicit staging
   URLs, including Index canonicals and Auth product returns. Tests use mocks
   for provider calls. Do not replace this with SQLite or live provider tests.
4. Successful checks write logs and `gates.json` under
   `.local/staging-test-1/release/`. The receipt records every commit, the
   workspace Makefile hash, public build URLs and log hashes. A failed rerun
   removes any prior receipt. A later source change invalidates the receipt.
   Complete local cross-app browser/SSR checks and obtain Claude's review
   before release. Record unfinished/unverified flows explicitly.
5. Push the verified commits to `staging`. No push to main or workflow-only
   main merge is required. Refresh tracking refs before publication.

`make staging-gate` uses the local infrastructure environment through the
existing Makefile; it does not select the server's staging environment.
It can take several minutes. Logs are local operator evidence; inspect them
before sharing outside the workspace.

## Capacity, runtime settings and approval

Ask the owner for the read-only SSH check first:
`free -h; nproc; df -h /srv; docker stats --no-stream`, plus read-only Docker
network subnet inspection. Reserve headroom for both production stacks before
choosing staging memory/CPU caps and `STAGING_NETWORK_CIDR`. The sample's 14 ×
256 MiB defaults are placeholders, not an approved capacity allocation.
Staging API runs one Gunicorn worker/four threads; upload extraction and
Qdrant may need larger caps, based on observed use.

The owner completes `deploy/staging/.env`, mode 0600. Use
`scripts/env-names-diff staging/.env` to report names only. Never print
resolved Compose environment or source the file into a chat-visible shell.
The server file supplies runtime hosts/origins/environment names, a
non-overlapping `STAGING_NETWORK_CIDR`, `COMPOSE_PROFILES=care,business`, tunnel
credentials and separate staging secrets. Limits, database and Qdrant names
have defaults. Image names and source SHAs come from the generated release.
Do not layer this file with production's `.env`.

Use separate Google/Brevo/AI credentials, Paystack **test** keys, no OPay,
server-only Access service credentials for Index, filesystem media and empty
mobile redirects. The owner configures the seven DNS/Access hosts and the
webhook bypass for exactly `/billing/webhook/paystack/`. Access secrets
must never appear in VITE build arguments or browser assets.

Present the source manifest, Compose/Caddy diff, approved limits/CIDR,
paths/volumes, backup/bootstrap order and rollback for review. Ask once for
publication, env/config transfer and first rollout as one explicit sequence.
Read-only SSH capacity approval alone does not authorize that sequence.
Bounded live Google/email/AI/Paystack checks need their own stated call/spend
scope unless included in the owner's explicit approval.

## Publish approved images locally

Authenticate Docker to GHCR with package-write rights outside recorded shell
output. Supply `UI_BUILD_TOKEN` securely in the environment with read access
to private `@fildah/ui`; never put its value on a command line. On the VPS,
prepare separate GHCR read access without forwarding the local write token.
The local host needs Docker Buildx, network access and enough disk for seven
Linux amd64 builds. No images are built on the VPS.

Run `make staging-publish` from the workspace root only after owner approval.
It refuses a dirty/unpushed source, a mismatched gate receipt or modified gate
logs. Build contexts are `git archive` exports of the verified commits, so
ignored `.env` files and node_modules cannot enter. Private dependency access
uses a BuildKit secret. It pushes `staging-<full-sha>` tags, inspects the
published digests and writes:

- `staging.release`: seven source/config SHAs and seven source-tagged,
  digest-pinned image references, plus the config archive hash; no secrets.
- `deploy-<deploy-sha>.tar`: committed Compose, staging Caddy and scripts only.

Treat a partial publication as incomplete. No release is written until all
seven images succeed. Keep the receipt, logs, release file, archive and shared
Makefile together as the release evidence. Tags are convenient names; the
rollout pulls by digest so a later tag overwrite cannot substitute code.

## Approved bootstrap and rollout

The operator chooses the actual SSH destination from the owner's known host
configuration, with existing trusted host-key verification. Do not disable
host-key checking or trust an unverified `ssh-keyscan` result.

1. Create `/srv/fildah/staging` and `/srv/fildah/backups/staging` if absent;
   do not overwrite an existing deployment. Copy only the owner's staging env
   to `/srv/fildah/staging/.env`, mode 0600. Preserve any existing staging env.
2. Transfer the reviewed archive and release file into a separate upload
   directory. Verify the archive SHA-256 against `CONFIG_SHA256` in the release.
   Extract `scripts/` into that upload directory for execution.
   Keep the archive and release file outside `/srv/fildah/staging`.
3. Over the approved SSH session, `cd /srv/fildah/staging` and run
   `bash /absolute/upload/scripts/rollout-staging /absolute/upload/deploy-SHA.tar /absolute/upload/staging.release`.
   It takes a nonblocking rollout lock, validates source/digest fields and
   archive paths/hash, then validates the candidate Compose config without
   displaying secrets. No production env/configuration is loaded.
4. The script captures production and RxChat container IDs, status and start
   timestamps. On an existing staging stack it stops staging writers, dumps
   PostgreSQL and validates the dump listing, stops Redis/Qdrant, and archives
   non-Postgres staging volumes read-only. This causes staging downtime.
   It preserves old config/release beside the backup. A stopped prior database
   or orphan staging volumes abort first-bootstrap detection. First bootstrap
   requires no existing staging containers or volumes.
5. Install the reviewed config/release, pull pinned images, start stores,
   migrate, sync platform settings and start staging. Verify API health,
   exact frontend build SHAs, worker pings, all 14 running services, no
   published ports, and unchanged production/RxChat IDs/start timestamps.
   A failure leaves backups and any stopped staging services for investigation;
   there is no automatic restore, volume deletion or production action.
6. Create the owner's staging superuser interactively if needed; configure
   `ConsoleEmail`, verified staging sender, AI routes/entitlements and Paystack
   test mode in staging Console. These are staging data changes, not seeds
   copied from production. Run `console_access_report`.

For approved manual inspection always use both isolated env files:

```sh
cd /srv/fildah/staging
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release config --quiet
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release ps
```

## Verify online and roll back

Before testers, record seven-host Access admission, OPTIONS/authenticated
CORS, host-only cookies, production-session isolation, Index anonymous SSR
with server Access credentials, signup/login/logout/reset/validated returns,
usernames, Index public/private routes, Business public/workspace routes,
Console permissions, queued upload and timed SSE. Check browser network for
PostHog and production API/Auth destinations. Approved Paystack test checkout
must return to staging Index; verify valid/invalid/duplicate webhooks.
A worker ping or health endpoint alone does not prove those flows.
Business remains an unfinished routing scaffold.

For image rollback, review migration compatibility first; newer data remains.
Use the retained previous config archive and digest-pinned release, rerun the
same approved rollout procedure and take another backup. `.release.previous`
alone does not restore an older Compose config. Never assume an older image
can read a newly migrated database.

Database/volume restore is a separate destructive, owner-approved operation.
First verify the exact backup in an isolated disposable database/store and
confirm schema/counts and image compatibility. Stop only staging writers;
take another safety backup, restore only the explicitly approved staging
stores, validate, then reopen staging. No tool here automatically runs
`pg_restore`, deletes a volume, touches production or reverses migrations.
The production folder move and Chat 0 production detach/purge rollout remain
separate owner-gated work.

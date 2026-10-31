# Fildah staging: local builds and direct SSH transfer

Staging runs in `/srv/fildah/staging`, Compose project `staging`, with seven
`fsandcube-*` hosts through the Cloudflare Tunnel and no published host ports.
Production keeps its existing GHCR/CI release process and project `deploy`.
The owner's latest instruction supersedes staging GHCR publication: build
locally, stream images directly to the VPS, keep only current staging tags.
There is no staging image rollback/history; rebuild and redeploy when needed.

## Verify and build locally

1. Use clean, committed `staging` checkouts. Fetch `origin/staging` in each
   source repository and push verified changes. No main push/merge is needed.
2. Run `make staging-plan`, then `make staging-gate`. The gate checks the full
   API release batch on fresh local Docker Postgres test databases, normal-
   hasher auth tests, frontend lint/types/tests/builds, Care/Index contracts
   and budgets, and Docker-backed deploy configuration/isolation tests.
   No SQLite or live providers. Exact source commits, public build URLs,
   Makefile and log hashes are recorded in `.local/staging-test-1/release/`.
   Unchanged successful checkpoints can be reused; changed inputs invalidate
   the affected gate. Record local browser and cross-app smoke evidence too.
3. Supply `UI_BUILD_TOKEN` securely in the process environment for the private
   UI source dependency. A source-read GitHub token is sufficient; no package
   registry-write credential or Docker GHCR login is needed for staging.
   Never put token values in arguments or logs.
4. Run `make staging-build`. Only committed `git archive` exports enter build
   contexts. BuildKit receives the UI token as a secret. Every image is built
   for Linux amd64 with staging URLs, a source revision label and `--load`.
   No application image is pushed or pulled from a registry.
5. The generated `staging.release` records source SHAs, local image tags and
   exact Docker image IDs, plus the config archive SHA-256. The committed-only
   `deploy-<deploy-sha>.tar` contains Compose, staging Caddy and operator scripts.
   The release is written only after all seven images succeed and inputs are
   rechecked. Current tags are `fildah-staging/<package>:current`.

## Runtime and capacity

Owner-approved SSH capacity checks precede rollout: memory, CPUs, disk, Docker
usage and network/host routes. Set bounded service memory/CPU limits and an
unused `STAGING_NETWORK_CIDR`, reserving production headroom. No builds run on
the VPS. The initial allocation totals 2768 MiB on the inspected 7.8 GiB host.

The isolated staging `.env` is mode 0600 and is never layered with production.
It supplies staging hosts/origins, `FILDAH_ENVIRONMENT=staging`,
`CONSOLE_ENVIRONMENT=Staging`, `COMPOSE_PROFILES=care,business`, the tunnel token,
separate runtime credentials and the current local `*_IMAGE` tags shown in
`staging.env.sample`. Image tags are also supplied by the current release.
Use `scripts/env-names-diff staging/.env` for missing names only; never display
expanded Compose environment or credential values. Use staging Google/Brevo/AI
credentials, Paystack test keys, no OPay, filesystem media and no mobile return
URIs. Index's Access service token belongs only on the server, scoped to the
staging API. Configure seven Access tester hosts, credentialed API CORS and
only the exact Paystack webhook bypass. Live provider tests need explicit
call/spend approval.

## Transfer and roll out

The owner authorizes SSH, deployment and staging secret transfer. Use the
known VPS host key; never disable host verification. Preserve existing staging
env files unless an update is authorized. Create staging and backup directories
with private permissions. The staging-only `.env` is transferred separately;
no environment file enters an image or the config archive.

1. Stream the current images with:
   `bash deploy/scripts/transfer-staging-images root@HOST CONFIG_TAR RELEASE_FILE`.
   This validates the config/release and local image IDs/revisions, then runs
   `docker save | gzip | ssh docker load` under the server rollout lock. It does not
   save an image tar archive or publish images. Failed transfers abort rollout.
2. Copy the config archive and release to a separate temporary upload directory
   on the VPS. Extract its `scripts/` there; do not execute a rollout script
   from the directory that the script overwrites.
3. From `/srv/fildah/staging`, run
   `bash /absolute/upload/scripts/rollout-staging /absolute/upload/config.tar /absolute/upload/staging.release`.
   The script verifies exact loaded IDs and revision labels before any staging
   service changes, validates archive paths/hash, takes a lock and checks the
   candidate Compose in a clean process environment without displaying secrets.
4. Existing staging writers stop before a validated logical Postgres dump.
   Redis stops before non-Postgres volume copies. Only staging volumes
   are backed up; no volumes are deleted. A stopped prior Postgres or orphan
   staging volumes abort bootstrap with a diagnostic. First bootstrap requires
   no existing staging containers/volumes.
5. Install current config/release, pull only public infrastructure images,
   start stores, rebuild indexes once if the Postgres collation changed, migrate
   and sync settings, then start all services. Every
   application service has `pull_policy: never`. Verify API and embedding-service health, frontend
   build SHAs, exact running image IDs, worker pings, all 14 services, no host
   ports and unchanged non-staging IDs/states/start times. Failure leaves
   staging backups for investigation; production is never restored or modified.

   Alpine databases have no recorded libc version. PostgreSQL refuses to
   refresh that NULL version to Debian's version, so `refresh-collation`
   records a successful reindex in a per-database `.fildah-collation-<oid>`
   marker in `PGDATA`. It reindexes again if the actual library version changes.
   Already versioned databases use PostgreSQL's normal refresh command.
6. After success, discard the upload artifacts. The current `.release` and
   installed config describe the running deployment; no previous image/config
   release pair is retained. Only untagged images carrying the explicit staging
   label are eligible for bounded non-force image cleanup; no global prune.
   Data backups are independent of image history and remain preserved.

For manual inspection always use both explicit staging files:

```sh
cd /srv/fildah/staging
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release config --quiet
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release ps
```

## Online verification

Record all seven hosts, owner/tester Access admission, API service-token access,
CORS/OPTIONS, host-only cookies, production-session isolation, Index anonymous
SSR, signup/login/logout/reset/Google and validated returns, usernames, Index
ownership routes, Business placeholders/workspaces, Console permissions,
queued uploads and timed SSE. Browser requests must use staging API/Auth and
contain no PostHog. Health or worker pings alone do not prove these flows.
Separate deterministic/local passes from approved live provider checks and
unverified behavior. Business remains a routing scaffold; Care's rebuild and
zero-retention work remain separate. Before testers, complete the existing
Google round-trip prerequisite. Configure a staging superuser, verified email,
AI routing and Paystack test mode using staging data only.

There is no automated image rollback. Database/volume restoration is a separate
destructive owner-approved operation requiring verified backups and image/schema
compatibility. The live production layout and product boundary are documented in
[vps-layout.md](vps-layout.md). Production and staging remain separate projects.

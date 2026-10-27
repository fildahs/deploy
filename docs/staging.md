# Fildah staging: bootstrap, rollout and recovery

Project **staging**, folder **/srv/fildah/staging**, backup root
**/srv/fildah/backups/staging**. All seven `fsandcube-*` hosts are behind
Cloudflare Access and its `fildah-staging` tunnel. This stack publishes no
host ports and uses only `staging_*` volumes and its own bridge network.

These are operator instructions, not authorization to execute production or
staging deployment operations. Follow the owner's requested release sequence.
The existing Fildah production folder is still `/srv/fildah/deploy`, project
`deploy`; `/srv/fildah/production` is the agreed eventual folder. Its move
remains separate from this staging rollout. Never sync staging files into
production while setting up staging.

## Before bootstrap

1. Obtain Claude's review of the config and Business changes, then the owner's
   commit/push request. Keep the chosen full commit SHA for each source repo
   and deploy config; a later code fix invalidates its prior release gate.
2. Fill the missing names reported by `scripts/env-names-diff staging/.env`.
   This reports names only. Use `staging.env.sample` for the complete schema;
   never print a resolved real Compose environment. Optional unused S3 and
   OPay values stay empty; filesystem media and Paystack test mode are used.
   Generate URL-safe infrastructure passwords for interpolated database URLs.
3. The owner supplies separate staging Google, Brevo and AI keys, Paystack
   test keys, tunnel token and server-only Access service token. Use Google
   callbacks from the setup guide. The webhook bypass covers exactly
   `/billing/webhook/paystack/`, never its parent paths.
4. Refresh read-only VPS capacity/network evidence with owner approval.
   Placeholder resource limits and `STAGING_NETWORK_CIDR` must be reviewed
   against all live stacks. Do not choose overlapping CIDRs.
5. Configure GitHub environment `staging` in deploy and all six source repos.
   Source URL Variables are listed in the execution plan. Deploy needs its
   scoped SSH/host, registry-read and Actions-read credentials. Never place
   the Access secret into any `VITE_*` value or GitHub public Variable.
6. Present the exact manifest and ask the owner for the sequence: env copy,
   staging image CI, bootstrap and first rollout. A checks-only CI request
   does not authorize publication or deployment.

## Bootstrap (approved server operations)

1. Clone deploy's `staging` branch into `/srv/fildah/staging`. Do not overwrite
   an existing folder. Confirm `pwd -P` exactly matches that path.
2. Copy the owner's staging env to `/srv/fildah/staging/.env`, mode 0600.
   Local Fildah still reads `deploy/.env`; no local environment selector exists.
3. After approved source CI/image publication, run the manual Deploy Staging
   workflow on `staging`, supplying full deploy/api/auth/care/business/index/
   fildah SHAs. API and both worker images share the API SHA. Images use
   `staging-<40-character SHA>`; no mutable staging tags are accepted.
4. The gate checks the latest successful staging CI for every selected SHA,
   checks the test and publish jobs in the same source run, and verifies all
   seven registry manifests before SSH. First bootstrap has no database to
   back up; it is accepted only when there are no existing staging volumes.
   A stopped pre-existing staging database aborts instead of skipping backup.
5. The rollout backs up the existing DB, syncs files without `.env` or
   deletion, saves `.release.previous`, writes `.release`, pulls, starts only
   infrastructure, migrates, runs `sync_platform_settings`, starts the app
   stack and checks health. Production container IDs are compared
   before/after; neither is restarted by this workflow.
6. Create the owner's superuser interactively. If their email is outside
   `@fildah.com`, add a `ConsoleEmail` row. Run `console_access_report`.
   Set `email.otp_mail` / `email.support_mail` to the verified staging sender;
   verify seeded AI providers/models and route entitlements in Console.
   Enable Paystack **test** mode and keep OPay disabled.

For manual approved operations, always use:

```sh
cd /srv/fildah/staging
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release config --quiet
docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release ps
```

Do not run bare `config` against a real env. Before testers, complete Chat 4's
Access/CORS/cookie/SSO/SSR/Paystack/queue/SSE checks. Live email/AI calls need
bounded owner approval. Business is an unfinished routing shell, not a launch
of Merchant or Professional functionality.

## Rollback

Read only the SHA/image manifest `.release.previous` (it contains no secrets),
then re-dispatch Deploy Staging with those source/deploy SHAs. The same exact
CI, publish-job and immutable-image gates apply. Keep backups and newer data.
There is no automatic database restore. Reverting an image does not reverse
schema migrations; assess compatibility before rollout.

## Database restore (separate owner-approved operation)

Stop staging writers only. Take another staging DB backup and verify the
chosen prior backup in an isolated disposable restore database before changing
live staging. With explicit approval for the exact destination and destructive
restore, restore using the standalone staging project's Postgres service;
check counts, schema compatibility and frontend/backend behavior before
reopening staging. Never use production's containers, volumes or database.
No workflow runs `pg_restore` automatically, deletes volumes or touches
`/srv/fildah/backups` outside its `staging/` subfolder.

After the owner approves the exact backup/destination and the isolated restore
check, the manual live-staging restore commands are:

```sh
cd /srv/fildah/staging
# Set STAGING_DB_BACKUP to the exact owner-approved dump path.
test -n "$STAGING_DB_BACKUP"
test -s "$STAGING_DB_BACKUP"
compose=(docker compose -p staging -f compose.yml -f compose.staging.yml --env-file .env --env-file .release)
"${compose[@]}" stop api worker attachment-worker billing-beat
umask 077
STAGING_RESTORE_SAFETY_DIR="$(mktemp -d /srv/fildah/backups/staging/manual-restore.XXXXXX)"
"${compose[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$STAGING_RESTORE_SAFETY_DIR/database.dump"
"${compose[@]}" exec -T postgres sh -c 'pg_restore --exit-on-error --single-transaction --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$STAGING_DB_BACKUP"
# Verify restored schema/counts and selected image compatibility before reopening.
"${compose[@]}" up -d api worker attachment-worker billing-beat
```

Use a unique pre-restore backup filename per operation rather than overwriting
a prior backup. An unsuccessful restore rolls its transaction back; investigate
before restarting writers. Restoring does not delete staging volumes.

## Production folder move

The current production folder is `/srv/fildah/deploy`. The eventual move to
`/srv/fildah/production` retains project `deploy` and needs separate owner
approval, a fresh backup, updated bind paths and reviewed effective config.
The Chat 0 production rollout must complete before dispatching the simplified
production workflow; follow coordination's execution plan and release handoff.

## GitHub workflow availability

`workflow_dispatch` must exist on the repository's default branch. After
Claude review, request the owner's approval for deploy `staging` → `main`.
Merge runs checks only; it does not publish images or deploy. Baseline
production Compose and adapted Caddy JSON compatibility tests are committed
under `tests/`; they verify repository defaults, not a replacement for the
separate production rollout described above.

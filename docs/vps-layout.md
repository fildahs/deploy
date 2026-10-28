# VPS runtime layout

The VPS stores deployment configuration and data volumes. API and web source is
built into images away from the host; no app source checkout is needed at
runtime. `compose.local.yml` is for development and must not be used on the VPS.

```text
/srv/fildah/
  production/       Compose project `deploy`: compose.yml, Caddyfile, .env (0600)
                    production-compose and routine deployment scripts
  staging/          Compose project `staging`: compose.yml, staging override,
                    Caddyfile.staging, .env (0600), .release and rollout scripts
  backups/
    production/     dated production configuration/data backups
    staging/        dated staging rollout backups
    fresh-20261027…/ owner-authorized verified full backup and private cleanup record
  archive/
    reference-documents/ preserved source/reference documents
/srv/rxchat-open/   Compose project `rxchat`, its own .env (0600) and backup
```

The Compose project names remain `deploy`, `staging` and `rxchat`. This keeps
existing named-volume identities stable. Each project reads only its own
host-managed `.env`. Never commit, display, or copy those files into images.
Staging is not layered with production configuration.

## Production and RxChat boundary

Fildah production has ten services. The former HealthScout frontend and stopped
Fildah RxChat frontend are removed. The retired Fildah RxChat and HealthScout
origin settings/defaults are absent from the running API source and production
environment; the API does not return CORS approval for either origin. The old
`/chat/` API route returns 404.

Standalone RxChat remains a separate seven-service Compose project at
`/srv/rxchat-open`. Its web container joins `deploy_default` with alias
`rxchat-web` so the existing Fildah Caddy can serve `rxchat.fildah.com`; the
RxChat API is addressed by its unique container name `rxchat-api-1`. No
production API, scheduler or configuration file is loaded from the RxChat
folder. This is the intentional public-ingress link between the products.

All reviewed old RxChat user data and HealthScout rows/media/cache were removed
from Fildah while account records, shared KEEP tables and the public Index
corpus were preserved. The current API migration history may retain empty
HealthScout tables temporarily; the existing Index migration removes them when
that release is applied. No manual follow-up cleanup is required.

## Operations and backups

The production workflow uses `/srv/fildah/production` and writes snapshots under
`/srv/fildah/backups/production`. Staging rollout snapshots go under
`/srv/fildah/backups/staging`. The one-time cleanup removed directories whose
contents predated 2026-10-27 in Africa/Lagos; backups dated 2026-10-27 and later
remain. There is no automatic backup deletion or global Docker prune.

Production, staging and the six non-web standalone RxChat containers retained
their IDs and named volumes during cleanup. Production now runs with its own
scheduler configuration. The staging containers were left unchanged. The
verified full backup and private operational evidence are under
`backups/fresh-20261027…/`; keep permissions restricted and never publish its
environment or Docker-inspection snapshots.

Use the repository's release workflow and the exact-CI gates for future changes.
Do not recreate compatibility paths under `/srv/fildah/deploy` or the retired
legacy scheduler/proxy overrides.

# Fildah production deployment

Production runs in `/srv/fildah/production`, project `deploy`, using immutable
API/worker images selected in the host-managed `.env`. Run `./production-compose`
for owner-approved operations. Source application folders are unnecessary.

This detach-only release keeps the existing Auth/marketing applications and
stores. It removes the retired HealthScout and old shared RxChat web services,
legacy scheduler wrapper and cross-product overrides. Standalone RxChat joins
`deploy_default` from its own configuration with alias `rxchat-web`; Fildah only
retains its single shared-ingress Caddy site.

Only account, platform, marketing and health APIs are public until the product
release. Retired endpoints return 404 and cannot recreate purged data.

API/worker source removes retired origin definitions and mobile defaults. No
blank legacy-variable overrides or one-off purge command belong in the release.
Current Qdrant collection identifiers remain unchanged to preserve public corpus.

Main pushes run checks only. Image publication and production deployment are
manual, owner-approved operations requiring successful exact-commit CI. Never
promote unfinished staging product applications as part of this release.

Backups live under `/srv/fildah/backups/production` and `/srv/fildah/backups/staging`;
the verified 2026-10-27 three-stack backup is retained separately under
`/srv/fildah/backups/fresh-20261027T231205+0100`. Pre-today backups were removed
with an explicit reviewed manifest. No recurring deletion is enabled.

## Initial detach transition

The routine deployment workflow is intentionally blocked until initial maintenance
is complete: it requires `scripts/compose-production` to be installed and the old
`legacy/` directory to be gone. Do not bootstrap this transition with rsync or git
reset while the current scheduler still mounts host state. The separately reviewed
maintenance procedure preserves that state into the existing media volume, runs
the account-preserving purge, installs CI-verified immutable API/worker images and
this exact configuration, recreates services and validates ingress before retiring
host artifacts. Only then can the routine workflow run. Owner approval of main
merges and successful exact-commit API/configuration CI are prerequisites.

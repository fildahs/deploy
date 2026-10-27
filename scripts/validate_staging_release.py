"""Validate a staging release and configuration archive before any mutation."""
import hashlib
import pathlib
import re
import sys
import tarfile


def validate(bundle, release):
    values = {}
    for line in release.read_text().splitlines():
        key, value = line.split('=', 1)
        if key in values:
            raise SystemExit('Duplicate release field')
        values[key] = value
    sources = {'API', 'AUTH', 'CARE', 'BUSINESS', 'INDEX', 'FILDAH', 'DEPLOY'}
    images = {'FILDAH_API_IMAGE': ('fildah-api', 'API'), 'FILDAH_WORKER_IMAGE': ('fildah-api-worker', 'API'),
              'AUTH_WEB_IMAGE': ('auth-web', 'AUTH'), 'CARE_WEB_IMAGE': ('care-web', 'CARE'),
              'BUSINESS_WEB_IMAGE': ('business-web', 'BUSINESS'), 'INDEX_WEB_IMAGE': ('index-web', 'INDEX'),
              'FILDAH_WEB_IMAGE': ('fildah-web', 'FILDAH')}
    if set(values) != {s + '_SHA' for s in sources} | set(images) | {'CONFIG_SHA256'}:
        raise SystemExit('Unexpected or missing release fields')
    for source in sources:
        if not re.fullmatch('[0-9a-f]{40}', values[source + '_SHA']):
            raise SystemExit('Invalid source SHA')
    for key, (package, source) in images.items():
        expected = re.escape('ghcr.io/fildahs/' + package + ':staging-' + values[source + '_SHA']) + '@sha256:[0-9a-f]{64}'
        if not re.fullmatch(expected, values[key]):
            raise SystemExit('Release images must match sources and be digest pinned')
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != values['CONFIG_SHA256']:
        raise SystemExit('Config bundle hash mismatch')
    with tarfile.open(bundle) as archive:
        names = archive.getnames()
        if len(names) != len(set(names)) or not {"compose.yml", "compose.staging.yml", "Caddyfile.staging", "scripts/assert_staging.py", "scripts/rollout-staging", "scripts/validate_staging_release.py"} <= set(names):
            raise SystemExit("Missing or duplicate config entries")
        for item in archive:
            name = pathlib.PurePosixPath(item.name)
            if name.is_absolute() or '..' in name.parts or not (item.isfile() or item.isdir()):
                raise SystemExit('Unsafe archive entry')
            if item.name not in ('compose.yml', 'compose.staging.yml', 'Caddyfile.staging', 'scripts') and not item.name.startswith('scripts/'):
                raise SystemExit('Unexpected config entry')


if __name__ == "__main__":
    validate(*map(pathlib.Path, sys.argv[1:]))

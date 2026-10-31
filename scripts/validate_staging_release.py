"""Validate a staging release and configuration archive before any mutation."""
import hashlib
import argparse
import json
import pathlib
import re
import sys
import subprocess
import tarfile


def validate(bundle, release, check_images=False):
    values = {}
    for line in release.read_text().splitlines():
        key, value = line.split('=', 1)
        if key in values:
            raise SystemExit('Duplicate release field')
        values[key] = value
    sources = {'API', 'AUTH', 'CARE', 'BUSINESS', 'INDEX', 'FILDAH', 'DEPLOY'}
    images = {'FILDAH_API_IMAGE': ('fildah-api', 'API'), 'FILDAH_WORKER_IMAGE': ('fildah-api-worker', 'API'),
              'EMBEDDINGS_IMAGE': ('fildah-embeddings', 'API'),
              'AUTH_WEB_IMAGE': ('auth-web', 'AUTH'), 'CARE_WEB_IMAGE': ('care-web', 'CARE'),
              'BUSINESS_WEB_IMAGE': ('business-web', 'BUSINESS'), 'INDEX_WEB_IMAGE': ('index-web', 'INDEX'),
              'FILDAH_WEB_IMAGE': ('fildah-web', 'FILDAH')}
    if set(values) != {s + '_SHA' for s in sources} | set(images) | {key + '_ID' for key in images} | {'CONFIG_SHA256'}:
        raise SystemExit('Unexpected or missing release fields')
    for source in sources:
        if not re.fullmatch('[0-9a-f]{40}', values[source + '_SHA']):
            raise SystemExit('Invalid source SHA')
    for key, (package, source) in images.items():
        if values[key] != 'fildah-staging/' + package + ':current' or not re.fullmatch('sha256:[0-9a-f]{64}', values[key + '_ID']):
            raise SystemExit('Release images must be local staging tags with exact image IDs')
        if check_images:
            try:
                info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', values[key]], text=True, stderr=subprocess.DEVNULL))[0]
                if info['Id'] != values[key + '_ID'] or info['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != values[source + '_SHA']:
                    raise SystemExit('Loaded staging image identity or revision mismatch: ' + key)
            except (subprocess.CalledProcessError, ValueError, KeyError, IndexError):
                raise SystemExit('Cannot inspect loaded staging image: ' + key) from None
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != values['CONFIG_SHA256']:
        raise SystemExit('Config bundle hash mismatch')
    with tarfile.open(bundle) as archive:
        names = archive.getnames()
        if len(names) != len(set(names)) or not {"compose.yml", "compose.staging.yml", "Caddyfile.staging", "scripts/assert_staging.py", "scripts/rollout-staging", "scripts/validate_staging_release.py", "scripts/refresh-collation"} <= set(names):
            raise SystemExit("Missing or duplicate config entries")
        for item in archive:
            name = pathlib.PurePosixPath(item.name)
            if name.is_absolute() or '..' in name.parts or not (item.isfile() or item.isdir()):
                raise SystemExit('Unsafe archive entry')
            if item.name not in ('compose.yml', 'compose.staging.yml', 'Caddyfile.staging', 'scripts') and not item.name.startswith('scripts/'):
                raise SystemExit('Unexpected config entry')
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=pathlib.Path)
    parser.add_argument('release', type=pathlib.Path)
    parser.add_argument('--check-images', action='store_true')
    args = parser.parse_args()
    validate(args.bundle, args.release, args.check_images)

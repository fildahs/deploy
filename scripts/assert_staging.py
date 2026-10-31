"""Assert isolation of an expanded staging config without displaying it."""
import json
import sys


def assert_staging(config):
    assert config['name'] == 'staging', 'Project must be staging'
    services = config['services']
    assert {'cloudflared', 'care-web', 'business-web'} <= services.keys(), 'Required staging services missing'
    for name, service in services.items():
        assert not service.get('ports'), f'{name}: host ports forbidden'
        assert service.get('mem_limit') and float(service.get('cpus', 0)) > 0, f'{name}: resource limits required'
        assert set(service.get('networks', {})) == {'default'}, f'{name}: foreign network forbidden'
        if name in {'api', 'worker', 'attachment-worker', 'billing-beat', 'embeddings', 'auth-web', 'care-web', 'fildah-web', 'index-web', 'business-web'}:
            assert service.get('pull_policy') == 'never', f'{name}: application image pulls forbidden'
            assert service['image'].startswith('fildah-staging/') and service['image'].endswith(':current'), f'{name}: local staging image required'
        for mount in service.get('volumes', []):
            if mount.get('type') == 'bind':
                assert mount['source'].endswith('/Caddyfile.staging'), f'{name}: unexpected bind mount'
                assert not mount['source'].startswith(('/srv/fildah/deploy/', '/srv/fildah/production/')), f'{name}: production bind forbidden'
    for volume in config.get('volumes', {}).values():
        assert not volume.get('external') and volume['name'].startswith('staging_'), 'Foreign volume forbidden'
    for network in config.get('networks', {}).values():
        assert not network.get('external') and network['name'].startswith('staging_'), 'Foreign network forbidden'
    env = services['api']['environment']
    assert env['FILDAH_ENVIRONMENT'] == 'staging' and env['CONSOLE_ENVIRONMENT'] == 'Staging', 'Wrong API environment'
    assert not env.get('MOBILE_REDIRECT_URIS'), 'Mobile must be disabled'


if __name__ == '__main__':
    try:
        assert_staging(json.load(sys.stdin))
    except (AssertionError, KeyError, ValueError, TypeError) as error:
        # Only our code-owned assertion text, never the expanded environment.
        raise SystemExit('Staging configuration isolation check failed: ' + (str(error) if isinstance(error, AssertionError) else 'invalid configuration')) from None
    print('Staging isolation verified.')

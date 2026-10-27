"""Process-local release test settings; never imported by application runtime.

The broad pass uses cheap fixture password hashes; an additional auth pass
uses normal hashers. Both use fresh isolated local Docker PostgreSQL databases.
The root Makefile still supplies the local infrastructure configuration.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.conf import settings  # noqa: E402
from django.core.management import execute_from_command_line  # noqa: E402

normal = '--normal-hasher' in sys.argv
if normal:
    sys.argv.remove('--normal-hasher')
database = settings.DATABASES['default']
if database['ENGINE'] != 'django.db.backends.postgresql' or database['HOST'] != '127.0.0.1' or str(database['PORT']) != '5433':
    raise SystemExit('Release tests require the root Makefile local Docker Postgres')
database.setdefault('TEST', {})['NAME'] = 'test_fildah_staging_auth' if normal else 'test_fildah_staging_release'
if not normal:
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
execute_from_command_line(sys.argv[1:])

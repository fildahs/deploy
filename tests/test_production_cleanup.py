import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ProductionCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env={'PATH':os.environ['PATH'],'SECRET_KEY':'placeholder','QDRANT_API_KEY':'placeholder','POSTGRES_PASSWORD':'placeholder','FILDAH_API_IMAGE':'example.invalid/api:verified','FILDAH_WORKER_IMAGE':'example.invalid/worker:verified'}
        cls.config=json.loads(subprocess.check_output(['docker','compose','--env-file','/dev/null','-p','deploy','-f',str(ROOT/'compose.yml'),'config','--format','json'],env=env,text=True,stderr=subprocess.PIPE))

    def test_production_has_only_current_services_and_storage_identities(self):
        self.assertEqual(set(self.config['services']),{'api','worker','attachment-worker','billing-beat','auth-web','fildah-web','postgres','redis','qdrant','caddy'})
        self.assertEqual(self.config['name'],'deploy')
        self.assertEqual(set(self.config['networks']),{'default'})
        for v in self.config['volumes'].values():self.assertTrue(v['name'].startswith('deploy_'))

    def test_no_legacy_origin_overrides_or_scheduler_mounts(self):
        for name in ('api','worker','attachment-worker','billing-beat'):
            service=self.config['services'][name]
            for key in ('RXCHAT_ORIGINS','RXCHAT_MOBILE_ORIGINS','HEALTHSCOUT_ORIGINS'):
                self.assertNotIn(key,service['environment'])
            for mount in service['volumes']:self.assertEqual(mount['type'],'volume')
        self.assertEqual(self.config['services']['billing-beat']['command'],['celery','-A','config','beat','--loglevel=info','--schedule=/app/media/scheduler/celerybeat-schedule'])

    def test_proxy_exposes_current_apis_and_shared_ingress_only(self):
        caddy=(ROOT/'Caddyfile').read_text()
        self.assertNotIn('healthscout',caddy.lower())
        self.assertEqual(caddy.count('rxchat.fildah.com'),1)
        self.assertIn('reverse_proxy rxchat-web:80',caddy)
        self.assertIn('@active_api path /auth/* /account/* /config/* /health',caddy)
        self.assertIn('respond "Not found" 404',caddy)
        self.assertNotIn('rxchat-edge',caddy)

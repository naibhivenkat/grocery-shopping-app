"""Prove the integration harness refuses production/nonloopback configuration."""
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts'/'verify_emulator_journeys.py'
spec=importlib.util.spec_from_file_location('emulator_harness',path)
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)

class EmulatorGuardTests(unittest.TestCase):
    def config(self,host='127.0.0.1:8089',project='demo-localshop-validation'):
        return {'FIRESTORE_EMULATOR_HOST':host,'GCLOUD_PROJECT':project}
    def test_accepts_loopback_demo_project(self):
        for host in ('127.0.0.1:8089','localhost:8089','[::1]:8089'):
            self.assertEqual(harness.guard_environment(self.config(host)),'demo-localshop-validation')
    def test_refuses_missing_emulator_or_project(self):
        for env in ({},{'GCLOUD_PROJECT':'demo-localshop-validation'},{'FIRESTORE_EMULATOR_HOST':'127.0.0.1:8089'}):
            with self.assertRaises(ValueError):harness.guard_environment(env)
    def test_refuses_remote_hosts_and_malformed_authorities(self):
        for host in ('firestore.googleapis.com:443','192.168.1.2:8089','0.0.0.0:8089',
            'https://127.0.0.1:8089','127.0.0.1:8089/path','name:8089','127.0.0.1','127.0.0.1:99999',
            'user:password@127.0.0.1:8089','127.0.0.1.evil:8089'):
            with self.subTest(host=host),self.assertRaises(ValueError):harness.guard_environment(self.config(host))
    def test_refuses_real_or_malformed_project_and_conflicting_project_environment(self):
        for project in ('groceryapp-fe2ec','demo-','demo-INVALID','demo-local/project'):
            with self.assertRaises(ValueError):harness.guard_environment(self.config(project=project))
        env=self.config();env['FIREBASE_PROJECT_ID']='groceryapp-fe2ec'
        with self.assertRaises(ValueError):harness.guard_environment(env)
        env=self.config();env['GOOGLE_CLOUD_PROJECT']='demo-another'
        with self.assertRaises(ValueError):harness.guard_environment(env)

if __name__=='__main__':unittest.main()

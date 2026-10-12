import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ci_config',ROOT/'deploy/scripts/ci_configuration.py')
ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
class Guards(unittest.TestCase):
    def test_public_port_rejected(self):
        self.assertTrue(ci.validate({'services':{'db':{'ports':['5432:5432']}}}))
    def test_startup_migration_rejected(self):
        self.assertTrue(ci.validate({'services':{'backend':{'mem_limit':'1g','cpus':1,'restart':'unless-stopped','command':['npm','run','migrate']}}}))
    def test_literal_secret_rejected(self):
        self.assertTrue(ci.validate({'services':{'backend':{'mem_limit':'1g','cpus':1,'restart':'unless-stopped','environment':{'JWT_SECRET':'fixture'}}}}))
    def test_implicit_volume_rejected(self):
        self.assertTrue(ci.validate({'volumes':{'state':{}}}))
    def test_real_workflow_is_build_only(self):
        self.assertEqual(ci.workflow_errors((ROOT/'.github/workflows/container-validation.yml').read_text()),[])
    def test_production_secret_reference_rejected(self):
        text=(ROOT/'.github/workflows/container-validation.yml').read_text()
        self.assertTrue(ci.workflow_errors(text+'\n# secrets.DATABASE_URL'))
if __name__=='__main__':unittest.main()

import importlib.util,unittest,urllib.request
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('release_transport',ROOT/'deploy/scripts/apply_release.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ReleaseTransport(unittest.TestCase):
    def test_no_api_key_forwarding_on_redirect(self):
        request=urllib.request.Request('https://control.invalid/api/compose.update',headers={'x-api-key':'synthetic-test-only'})
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network in this test')):
            for code in (301,302,303,307,308):
                self.assertIsNone(m.NoRedirect().redirect_request(request,None,code,'redirect',{},'https://other.invalid/'))
if __name__=='__main__':unittest.main()

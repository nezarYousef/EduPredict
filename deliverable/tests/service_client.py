"""Trusted client used only by pre-existing behavior characterization tests."""
from fastapi.testclient import TestClient as BaseClient
KEY = 'test-only-edupredict-service-key-000'
class TestClient(BaseClient):
    __test__ = False
    def __init__(self, *args, **kwargs):
        kwargs['headers'] = {'X-Service-Key':KEY,'X-EduFusion-Role':'admin',**kwargs.get('headers',{})}
        super().__init__(*args, **kwargs)

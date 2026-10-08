import pytest
from service_client import KEY
@pytest.fixture(autouse=True)
def isolated_service_configuration(monkeypatch):
    monkeypatch.setenv('EDUPREDICT_SERVICE_KEY', KEY)

import pytest
from service_client import KEY
@pytest.fixture(autouse=True)
def isolated_service_configuration(monkeypatch):
    monkeypatch.setenv('EDUPREDICT_SERVICE_KEY', KEY)
    # Existing characterization tests exercise writes against mocked connections.
    # Production defaults to deny; the policy suite explicitly tests that default.
    monkeypatch.setenv('EDUPREDICT_ALLOW_DATABASE_WRITES', 'true')

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import admin_data
import main
import prediction_store
import student_data
from service_client import KEY
from test_api import FakePredictor, RESPONSE
from write_policy import require_database_writes


@pytest.mark.parametrize("value", [None, "", "false", "1", "yes", "unexpected"])
def test_default_and_unknown_values_deny(value, monkeypatch):
    if value is None:
        monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    else:
        monkeypatch.setenv("EDUPREDICT_ALLOW_DATABASE_WRITES", value)
    with pytest.raises(HTTPException) as error:
        require_database_writes()
    assert error.value.status_code == 403


def test_explicit_true_allows_only_the_application_guard(monkeypatch):
    monkeypatch.setenv("EDUPREDICT_ALLOW_DATABASE_WRITES", "true")
    require_database_writes()


@pytest.mark.parametrize("path,params", [
    ("/students/123/prediction", {}),
    ("/admin/clock/tick", {"code_module": "FIX", "code_presentation": "TEST"}),
    ("/admin/clock/reset", {"code_module": "FIX", "code_presentation": "TEST"}),
    ("/admin/predictions/run-demo", {}),
])
def test_authenticated_mutations_fail_before_data_or_inference(path, params, monkeypatch):
    monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "test-only-admin-key")
    monkeypatch.setattr(main, "predictor", FakePredictor())
    def unexpected(*args, **kwargs):
        pytest.fail("Disabled route reached a data or model operation")
    for name in ["build_student_prediction_request", "save_prediction", "update_clock", "run_demo_predictions"]:
        monkeypatch.setattr(main, name, unexpected)
    headers = {"X-Service-Key": KEY, "X-EduFusion-Role": "student",
               "X-EduFusion-Student-Id": "123", "X-Admin-Key": "test-only-admin-key"}
    response = TestClient(main.app).post(path, params=params, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Database writes are disabled."}


def test_disabled_writes_do_not_bypass_authentication(monkeypatch):
    monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "test-only-admin-key")
    client = TestClient(main.app)
    assert client.post("/students/123/prediction").status_code == 401
    assert client.post("/admin/clock/tick", params={"code_module": "FIX", "code_presentation": "TEST"}).status_code == 401
    assert client.post("/admin/predictions/run-demo").status_code == 401


def test_readonly_student_prediction_remains_available(monkeypatch):
    monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kw: (1, kw))
    monkeypatch.setattr(main, "save_prediction", lambda *args: pytest.fail("GET attempted persistence"))
    response = TestClient(main.app).get("/students/123/prediction", headers={
        "X-Service-Key": KEY, "X-EduFusion-Role": "student", "X-EduFusion-Student-Id": "123"})
    assert response.status_code == 200
    assert response.json() == RESPONSE.model_dump(mode="json")


def test_direct_persistence_helpers_deny_before_connection_or_sql(monkeypatch):
    monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    def unexpected(*args, **kwargs):
        pytest.fail("Disabled helper reached a connection or SQL")
    monkeypatch.setattr(student_data, "get_connection", unexpected)
    monkeypatch.setattr(admin_data, "get_connection", unexpected)
    class Cursor:
        execute = unexpected
    for call in [lambda: student_data.save_prediction(1, RESPONSE),
                 lambda: prediction_store.save_prediction_with_cursor(Cursor(), 1, RESPONSE),
                 lambda: admin_data.update_clock("FIX", "TEST"),
                 lambda: admin_data.run_demo_predictions(object())]:
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 403


def test_nonpersisting_scenario_post_remains_available(monkeypatch):
    from test_scenario import scenario
    monkeypatch.delenv("EDUPREDICT_ALLOW_DATABASE_WRITES", raising=False)
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kw: (1, kw))
    monkeypatch.setattr(main, "apply_scenario", lambda base, *args: base)
    monkeypatch.setattr(main, "save_prediction", lambda *args: pytest.fail("Scenario attempted persistence"))
    response = TestClient(main.app).post("/students/123/scenario-prediction", json=scenario().model_dump(), headers={
        "X-Service-Key": KEY, "X-EduFusion-Role": "student", "X-EduFusion-Student-Id": "123"})
    assert response.status_code == 200

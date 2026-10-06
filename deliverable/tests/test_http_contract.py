from fastapi.testclient import TestClient
import psycopg
import pytest

import main
import student_data
from test_api import FakePredictor, RESPONSE
from test_data_contract import ASSESSMENTS, BASE, VLE, RecordingConnection
from test_scenario import base_request, scenario


@pytest.mark.parametrize(
    "method,path,payload,detail",
    [
        ("get", "/health", None, "Model not loaded"),
        ("get", "/ready", None, "Prediction service is temporarily unavailable."),
        ("post", "/predict", base_request().model_dump(), "Model not loaded"),
        ("post", "/predict/batch", {"students": []}, "Model not loaded"),
        ("get", "/students/2026/prediction", None, "Model not loaded"),
        (
            "post",
            "/students/2026/scenario-prediction",
            scenario().model_dump(),
            "Model not loaded",
        ),
    ],
)
def test_model_not_loaded(monkeypatch, method, path, payload, detail):
    monkeypatch.setattr(main, "predictor", None)
    response = TestClient(main.app).request(
        method, path, **({"json": payload} if payload is not None else {})
    )
    assert response.status_code == 503
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "count,detail",
    [
        (0, "students list is empty"),
        (5001, "batch size exceeds limit of 5000 - split into smaller batches"),
    ],
)
def test_batch_limits(monkeypatch, count, detail):
    monkeypatch.setattr(main, "predictor", object())
    item = {"student_id": 2026, "request": base_request().model_dump()}
    response = TestClient(main.app).post(
        "/predict/batch", json={"students": [item] * count}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "error_type,database,status",
    [
        (psycopg.OperationalError, True, 503),
        (OSError, True, 503),
        (RuntimeError, True, 503),
        (ValueError, True, 500),
        (psycopg.OperationalError, False, 500),
        (RuntimeError, False, 500),
    ],
)
def test_safe_error_mapping_and_logging(error_type, database, status, caplog):
    error = main.service_error(
        "test stage", error_type("password=secret student=private"), database=database
    )
    assert error.status_code == status
    assert error.detail == (
        "Prediction data service is temporarily unavailable."
        if status == 503
        else "Prediction service is temporarily unavailable."
    )
    assert "secret" not in caplog.text + error.detail
    assert "private" not in caplog.text + error.detail
    assert "EduPredict test stage failed:" in caplog.text
    assert caplog.records[-1].name == "main"


@pytest.mark.parametrize(
    "configured,supplied,status,detail",
    [
        (None, None, 503, "ADMIN_API_KEY is not configured"),
        ("", "key", 503, "ADMIN_API_KEY is not configured"),
        ("key", None, 401, "Invalid admin key"),
        ("key", "wrong", 401, "Invalid admin key"),
        ("key", "key", 200, None),
    ],
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/admin/clock"),
        ("post", "/admin/clock/tick?code_module=BBB&code_presentation=2013B"),
        ("post", "/admin/clock/reset?code_module=BBB&code_presentation=2013B"),
        ("post", "/admin/predictions/run-demo"),
        ("get", "/admin/students/at-risk"),
    ],
)
def test_admin_auth_on_all_routes(
    monkeypatch, configured, supplied, status, detail, method, path
):
    if configured is None:
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ADMIN_API_KEY", configured)
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "list_clocks", lambda: [])
    monkeypatch.setattr(main, "update_clock", lambda **kwargs: kwargs)
    monkeypatch.setattr(main, "run_demo_predictions", lambda *args, **kwargs: {})
    monkeypatch.setattr(main, "list_latest_risk_students", lambda **kwargs: [])
    headers = {"x-admin-key": supplied} if supplied is not None else {}
    response = TestClient(main.app).request(method, path, headers=headers)
    assert response.status_code == status
    if detail:
        assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "change",
    [
        {"based_on_day": -1},
        {"extra": True},
        {"inputs": {"quiz_clicks": -1}},
        {"inputs": {"activity_days": 0}},
        {"inputs": {"latest_tma_score": 101}},
        {"inputs": {"tma_delay_days": -1}},
        {"inputs": {"new_submission_type": "Exam"}},
        {"inputs": {"extra": True}},
        {"activity": {"extra": []}},
        {"activity": {"quiz_clicks": [{"date": 60, "clicks": 0}]}},
    ],
)
def test_scenario_schema_rejections(monkeypatch, change):
    monkeypatch.setattr(main, "predictor", object())
    monkeypatch.setattr(
        main,
        "build_student_prediction_request",
        lambda **kwargs: pytest.fail("invalid input reached DB"),
    )
    payload = scenario().model_dump()
    payload.update(change)
    assert (
        TestClient(main.app)
        .post("/students/2026/scenario-prediction", json=payload)
        .status_code
        == 422
    )


def test_scenario_database_path_is_read_only(monkeypatch):
    # Exercise actual data access and due-date lookup, not just a mocked loader.
    read = RecordingConnection([BASE, VLE, ASSESSMENTS])
    due = RecordingConnection([{"date": 40}])
    connections = iter([read, due])
    monkeypatch.setattr(
        student_data, "get_connection", lambda: next(connections).connect()
    )
    monkeypatch.setattr(main, "predictor", FakePredictor())
    response = TestClient(main.app).post(
        "/students/2026/scenario-prediction", json=scenario().model_dump()
    )
    assert response.status_code == 200
    assert response.json() == RESPONSE.model_dump(mode="json")
    for connection in (read, due):
        assert "commit" not in connection.events
        statements = [
            event["sql"] for event in connection.events if isinstance(event, dict)
        ]
        assert statements
        assert all(sql.startswith("SELECT ") for sql in statements)


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/students/2026/prediction", None),
        ("post", "/students/2026/scenario-prediction", scenario().model_dump()),
    ],
)
def test_missing_enrollment(monkeypatch, method, path, payload):
    monkeypatch.setattr(main, "predictor", FakePredictor())

    def missing(**kwargs):
        raise LookupError("private lookup context")

    monkeypatch.setattr(main, "build_student_prediction_request", missing)
    response = TestClient(main.app).request(
        method, path, **({"json": payload} if payload else {})
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "No enrollment found for this student"}

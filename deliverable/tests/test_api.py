from contextlib import contextmanager
import sys
import types

import psycopg
from service_client import TestClient

# Route tests isolate the API from loading the model artifact at import time.
predictor_module = types.ModuleType("predictor")
predictor_module.EduPredictor = type("EduPredictor", (), {})
sys.modules["predictor"] = predictor_module

import main
sys.modules.pop("predictor")
from schemas import PredictResponse


RESPONSE = PredictResponse.model_validate(
    {
        "risk_probability": 0.92,
        "risk_level": "HIGH",
        "at_risk": 1,
        "recommended_action": "Contact student immediately",
        "explanation": ["Low engagement"],
        "threshold_used": 0.41,
        "model_confidence": {
            "day_of_course": 60,
            "closest_snapshot": 60,
            "expected_f1": 0.8,
            "expected_auc": 0.89,
        },
        "data_completeness": {
            "has_vle_data": True,
            "has_assessment_data": True,
            "features_available": 29,
            "features_total": 31,
            "completeness_pct": 93.5,
        },
    }
)


class FakePredictor:
    feature_cols = list(range(31))
    snapshots = [0, 30, 60, 90, 150]
    default_threshold = 0.41

    def predict(self, request):
        return RESPONSE


class FakeCursor:
    def __init__(self):
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement):
        self.statement = statement

    def fetchone(self):
        assert self.statement == "SELECT 1"
        return (1,)


class FakeConnection:
    def cursor(self):
        return FakeCursor()


@contextmanager
def working_connection():
    yield FakeConnection()


@contextmanager
def failed_connection():
    raise psycopg.OperationalError("password=secret host=private.example")
    yield


def test_health_is_model_liveness(monkeypatch):
    monkeypatch.setattr(main, "predictor", FakePredictor())
    assert TestClient(main.app).get("/health").json()["model_loaded"] is True


def test_readiness_success(monkeypatch):
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "get_connection", working_connection)
    response = TestClient(main.app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_database_failure_is_safe(monkeypatch, caplog):
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "get_connection", failed_connection)
    response = TestClient(main.app).get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Prediction data service is temporarily unavailable."}
    assert "private.example" not in response.text + caplog.text
    assert "secret" not in response.text + caplog.text
    assert "OperationalError" in caplog.text


def test_explicit_post_prediction_persists(monkeypatch):
    saved = []
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kwargs: (32603, kwargs))
    monkeypatch.setattr(main, "save_prediction", lambda enrollment_id, response: saved.append((enrollment_id, response)))
    response = TestClient(main.app).post(
        "/students/2026/prediction?code_module=BBB&code_presentation=2013B"
    )
    assert response.status_code == 200
    assert response.json()["risk_probability"] == 0.92
    assert saved == [(32603, RESPONSE)]


def test_student_database_failure_is_safe(monkeypatch, caplog):
    monkeypatch.setattr(main, "predictor", FakePredictor())

    def fail_load(**kwargs):
        raise psycopg.OperationalError("password=secret host=private.example")

    monkeypatch.setattr(main, "build_student_prediction_request", fail_load)
    response = TestClient(main.app).get("/students/2026/prediction?code_module=BBB&code_presentation=2013B")
    assert response.status_code == 503
    assert response.json() == {"detail": "Prediction data service is temporarily unavailable."}
    assert "private.example" not in response.text + caplog.text
    assert "secret" not in response.text + caplog.text


def test_prediction_save_failure_is_safe(monkeypatch):
    monkeypatch.setattr(main, "predictor", FakePredictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kwargs: (32603, kwargs))

    def fail_save(enrollment_id, response):
        raise psycopg.OperationalError("host=private.example")

    monkeypatch.setattr(main, "save_prediction", fail_save)
    response = TestClient(main.app).post("/students/2026/prediction")
    assert response.status_code == 503
    assert "private.example" not in response.text


def test_model_error_is_safe(monkeypatch):
    class FailedPredictor(FakePredictor):
        def predict(self, request):
            raise ValueError("sensitive input")

    monkeypatch.setattr(main, "predictor", FailedPredictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kwargs: (32603, kwargs))
    response = TestClient(main.app).get("/students/2026/prediction")
    assert response.status_code == 500
    assert "sensitive input" not in response.text

import hashlib
import json
from pathlib import Path

from service_client import TestClient
import pytest

import main
from characterization_cases import exact_frame, representative_requests
from schemas import BatchRequest, PredictRequest


FIXTURES = Path(__file__).parent / "fixtures"
REQUESTS = representative_requests()


@pytest.fixture(scope="module")
def real_predictor():
    from predictor import EduPredictor

    return EduPredictor()


def test_model_artifact_is_unchanged():
    from predictor import MODEL_PATH

    expected = json.loads((FIXTURES / "predictions.json").read_text())
    assert (
        hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == expected["model_sha256"]
    )


@pytest.mark.parametrize("name", REQUESTS)
def test_exact_features_and_full_prediction(name, real_predictor, monkeypatch):
    expected = json.loads((FIXTURES / "predictions.json").read_text())["cases"][name]
    request = REQUESTS[name]
    frame = real_predictor._build_features(request)
    assert exact_frame(frame) == expected["features"]
    # Compare the unrounded model probability as well as every response field.
    assert (
        float(real_predictor.model.predict_proba(frame)[0][1]).hex()
        == expected["raw_probability"]
    )
    assert (
        real_predictor.predict(request).model_dump(mode="json") == expected["response"]
    )
    monkeypatch.setattr(main, "predictor", real_predictor)
    response = TestClient(main.app).post(
        "/predict", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200
    assert response.json() == expected["response"]


@pytest.mark.parametrize("threshold", [None, 0.2, 0.9, 0.0, 1.1])
def test_batch_predictions_and_validation_preserved(
    threshold, real_predictor, monkeypatch
):
    # BatchRequest currently accepts out-of-range thresholds; preserve that behavior.
    request = BatchRequest.model_validate(
        {
            "students": [
                {"student_id": name, "request": value.model_dump()}
                for name, value in REQUESTS.items()
            ],
            "threshold": threshold,
        }
    )
    expected = json.loads((FIXTURES / "predictions.json").read_text())["batches"][
        str(threshold)
    ]
    monkeypatch.setattr(main, "predictor", real_predictor)
    response = TestClient(main.app).post(
        "/predict/batch", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200
    assert response.json() == expected


def test_openapi_contract():
    assert main.app.openapi() == json.loads((FIXTURES / "openapi.json").read_text())


def test_request_collection_defaults_and_validation():
    payload = {
        "day_of_course": 0,
        "demographics": REQUESTS["empty_0"].demographics.model_dump(),
    }
    first = PredictRequest.model_validate(payload)
    second = PredictRequest.model_validate(payload)
    assert first.model_dump() == {
        **payload,
        "vle_log": [],
        "assess_log": [],
        "threshold": None,
    }
    first.vle_log.append(REQUESTS["boundaries"].vle_log[0])
    assert second.vle_log == []
    for field in ("vle_log", "assess_log"):
        with pytest.raises(ValueError):
            PredictRequest.model_validate({**payload, field: None})


@pytest.mark.parametrize(
    "prob,threshold,level,action",
    [
        (0.699999, 0.41, "MEDIUM", "Monitor closely, send reminder"),
        (0.7, 0.9, "HIGH", "Contact student immediately"),
        (0.41, 0.41, "MEDIUM", "Monitor closely, send reminder"),
        (0.409999, 0.41, "LOW", "No action needed"),
    ],
)
def test_risk_and_action_boundaries(prob, threshold, level, action, real_predictor):
    assert real_predictor._risk_level(prob, threshold).value == level
    assert real_predictor._action(prob, threshold) == action


def test_startup_loads_real_model_and_health(monkeypatch, real_predictor):
    # test_api replaces the imported constructor, so explicitly restore the real one.
    monkeypatch.setattr(main, "EduPredictor", type(real_predictor))
    monkeypatch.setattr(main, "predictor", None)
    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "model_loaded": True,
            "feature_count": len(real_predictor.feature_cols),
            "snapshots": real_predictor.snapshots,
            "default_threshold": real_predictor.default_threshold,
        }

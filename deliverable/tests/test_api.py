import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
sys.path.insert(0, str(API_DIR))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    with client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["feature_count"] == 31
    assert body["default_threshold"] == 0.41


def test_predict_low_risk_payload():
    payload = {
        "day_of_course": 90,
        "demographics": {
            "code_module": "FFF",
            "gender_bin": 1,
            "disability_bin": 0,
            "age_numeric": 0,
            "edu_numeric": 2,
            "imd_numeric": 60.0,
            "num_of_prev_attempts": 0,
            "studied_credits": 60,
            "module_total_assessments": 13,
            "course_length": 269,
        },
        "vle_log": [
            {"date": 10, "sum_click": 300, "activity_type": "resource"},
            {"date": 50, "sum_click": 400, "activity_type": "forumng"},
            {"date": 90, "sum_click": 500, "activity_type": "quiz"},
        ],
        "assess_log": [
            {"date_submitted": 20, "score": 90, "assessment_type": "TMA", "date": 22},
            {"date_submitted": 60, "score": 92, "assessment_type": "CMA", "date": 62},
        ],
    }
    with client:
        response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["at_risk"] == 0
    assert body["risk_level"] == "LOW"
    assert body["threshold_used"] == 0.41


def test_batch_rejects_empty_students():
    with client:
        response = client.post("/predict/batch", json={"students": []})
    assert response.status_code == 422

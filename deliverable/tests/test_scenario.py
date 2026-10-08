from service_client import TestClient
import pytest

import main
from scenario_data import apply_scenario
from schemas import PredictRequest, ScenarioEvidence
from test_api import RESPONSE


def base_request():
    return PredictRequest.model_validate({
        "day_of_course": 60,
        "demographics": {
            "code_module": "BBB", "gender_bin": 0, "disability_bin": 0,
            "age_numeric": 1, "edu_numeric": 2, "imd_numeric": 50,
            "num_of_prev_attempts": 0, "studied_credits": 60,
            "module_total_assessments": 3, "course_length": 240,
        },
        "vle_log": [{"date": 1, "sum_click": 5, "activity_type": "resource"}],
        "assess_log": [{"date_submitted": 32, "score": 50, "assessment_type": "TMA", "date": 30}],
    })


def scenario(**changes):
    inputs = {"quiz_clicks": 9, "forum_clicks": 0, "resource_clicks": 0,
              "activity_days": 3, "latest_tma_score": 90,
              "new_submission_type": "CMA", "new_submission_score": 80,
              "new_submission_delay_days": 1}
    inputs.update(changes)
    return ScenarioEvidence.model_validate({
        "based_on_day": 60, "inputs": inputs,
        "activity": {"quiz_clicks": [{"date": 60, "clicks": 3},
                                      {"date": 59, "clicks": 3},
                                      {"date": 58, "clicks": 3}]},
    })


def test_overlay_uses_raw_model_evidence_without_mutating_actual_request():
    base = base_request()
    original = base.model_dump()
    calls = []
    def due(enrollment_id, assessment_type):
        calls.append((enrollment_id, assessment_type))
        return 40
    result = apply_scenario(base, scenario(), 32603, due)
    assert base.model_dump() == original
    assert [(e.date, e.sum_click, e.activity_type) for e in result.vle_log[1:]] == [
        (60, 3, "quiz"), (59, 3, "quiz"), (58, 3, "quiz")]
    assert [(a.date_submitted, a.score, a.assessment_type, a.date) for a in result.assess_log] == [
        (32, 90, "TMA", 30), (41, 80, "CMA", 40)]
    assert calls == [(32603, "CMA")]


@pytest.mark.parametrize("change", [
    {"based_on_day": 59},
    {"activity": {"quiz_clicks": [{"date": 60, "clicks": 9}]}},
])
def test_invalid_or_stale_evidence_rejected(change):
    evidence = scenario().model_dump()
    evidence.update(change)
    with pytest.raises(ValueError):
        apply_scenario(base_request(), ScenarioEvidence.model_validate(evidence), 32603, lambda *_: 40)


def test_scenario_route_invokes_model_without_saving_actual_prediction(monkeypatch):
    seen = []
    class Predictor:
        def predict(self, request):
            seen.append(request)
            return RESPONSE
    monkeypatch.setattr(main, "predictor", Predictor())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kwargs: (32603, base_request()))
    monkeypatch.setattr(main, "next_assessment_due_date", lambda *_: 40)
    monkeypatch.setattr(main, "save_prediction", lambda *_: pytest.fail("hypothetical result was persisted"))
    response = TestClient(main.app).post(
        "/students/2026/scenario-prediction?code_module=BBB&code_presentation=2013B",
        json=scenario().model_dump(),
    )
    assert response.status_code == 200
    assert response.json()["risk_probability"] == RESPONSE.risk_probability
    assert len(seen) == 1
    assert seen[0].assess_log[-1].score == 80


def test_scenario_route_rejects_invalid_activity(monkeypatch):
    monkeypatch.setattr(main, "predictor", object())
    monkeypatch.setattr(main, "build_student_prediction_request", lambda **kwargs: (32603, base_request()))
    evidence = scenario().model_dump()
    evidence["activity"]["quiz_clicks"][0]["clicks"] = 4
    response = TestClient(main.app).post("/students/2026/scenario-prediction", json=evidence)
    assert response.status_code == 422


def test_real_model_uses_changed_evidence_when_dependencies_are_available():
    pytest.importorskip("lightgbm")
    from predictor import EduPredictor
    predictor = EduPredictor()
    base = base_request()
    hypothetical = apply_scenario(base, scenario(), 32603, lambda *_: 40)
    real_features = predictor._build_features(base)
    scenario_features = predictor._build_features(hypothetical)
    assert real_features["total_clicks"].iloc[0] == 5
    assert scenario_features["total_clicks"].iloc[0] == 14
    assert scenario_features["quiz_clicks"].iloc[0] == 9
    assert scenario_features["avg_score"].iloc[0] == 85
    assert scenario_features["num_submitted"].iloc[0] == 2
    assert predictor.predict(base).risk_probability != predictor.predict(hypothetical).risk_probability

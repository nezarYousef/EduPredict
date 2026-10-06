"""Deterministic inputs and exact feature encoding for refactor regression tests."""

import math

from schemas import PredictRequest, ScenarioEvidence
from scenario_data import apply_scenario


def representative_requests():
    demographics = {
        "code_module": "BBB",
        "gender_bin": 0,
        "disability_bin": 0,
        "age_numeric": 1,
        "edu_numeric": 2,
        "imd_numeric": 50,
        "num_of_prev_attempts": 0,
        "studied_credits": 60,
        "module_total_assessments": 3,
        "course_length": 240,
    }
    requests = {}
    for day in (0, 1, 30, 60, 90, 150, 240):
        requests[f"empty_{day}"] = PredictRequest(
            day_of_course=day, demographics=demographics
        )
    evidence = {
        "day_of_course": 60,
        "demographics": demographics,
        "vle_log": [
            {"date": -1, "sum_click": 3, "activity_type": "resource"},
            {"date": 0, "sum_click": 0, "activity_type": "forumng"},
            {"date": 30, "sum_click": 60, "activity_type": "quiz"},
            {"date": 31, "sum_click": 4, "activity_type": "other"},
            {"date": 60, "sum_click": 17, "activity_type": "quiz"},
            {"date": 61, "sum_click": 999, "activity_type": "resource"},
        ],
        "assess_log": [
            {"date_submitted": 30, "score": 90, "assessment_type": "TMA", "date": 25},
            {"date_submitted": 30, "score": 39, "assessment_type": "CMA", "date": None},
            {"date_submitted": 60, "score": 40, "assessment_type": "Exam", "date": 65},
            {"date_submitted": 61, "score": 100, "assessment_type": "TMA", "date": 61},
        ],
    }
    requests["boundaries"] = PredictRequest.model_validate(evidence)
    for module in ("AAA", "CCC", "DDD", "EEE", "FFF", "GGG", "UNKNOWN"):
        requests[f"module_{module}"] = requests["boundaries"].model_copy(
            update={
                "demographics": requests["boundaries"].demographics.model_copy(
                    update={"code_module": module}
                )
            }
        )
    requests["override_low"] = requests["boundaries"].model_copy(
        update={"threshold": 0.01}
    )
    requests["override_high"] = requests["boundaries"].model_copy(
        update={"threshold": 0.99}
    )
    requests["future_only"] = PredictRequest.model_validate(
        {
            **evidence,
            "vle_log": evidence["vle_log"][-1:],
            "assess_log": evidence["assess_log"][-1:],
        }
    )
    requests["scenario_base"] = PredictRequest.model_validate(
        {
            **evidence,
            "vle_log": [{"date": 1, "sum_click": 5, "activity_type": "resource"}],
            "assess_log": [
                {
                    "date_submitted": 32,
                    "score": 50,
                    "assessment_type": "TMA",
                    "date": 30,
                }
            ],
        }
    )
    scenario = ScenarioEvidence.model_validate(
        {
            "based_on_day": 60,
            "inputs": {
                "quiz_clicks": 9,
                "activity_days": 3,
                "latest_tma_score": 90,
                "new_submission_type": "CMA",
                "new_submission_score": 80,
                "new_submission_delay_days": 1,
            },
            "activity": {
                "quiz_clicks": [{"date": d, "clicks": 3} for d in (60, 59, 58)]
            },
        }
    )
    requests["scenario_overlay"] = apply_scenario(
        requests["scenario_base"], scenario, 32603, lambda *_: 40
    )
    return requests


def exact_frame(frame):
    """Include dtypes, category metadata, NaNs and bit-exact floating-point values."""
    columns = []
    for name in frame.columns:
        series = frame[name]
        if str(series.dtype) == "category":
            values = series.tolist()
            categories = series.cat.categories.tolist()
        else:
            values = ["NaN" if math.isnan(float(v)) else float(v).hex() for v in series]
            categories = None
        columns.append(
            {
                "name": name,
                "dtype": str(series.dtype),
                "categories": categories,
                "values": values,
            }
        )
    return columns

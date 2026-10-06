"""Characterize database calls without touching production data."""

from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path

import pytest
from psycopg.types.json import Json

import admin_data
import student_data
from test_api import RESPONSE


FIXTURES = Path(__file__).parent / "fixtures"
BASE = {
    "enrollment_id": 32603,
    "id_student": 2026,
    "code_module": "BBB",
    "code_presentation": "2013B",
    "day_of_course": 60,
    "gender": "m",
    "disability": "y",
    "age_band": "35-55",
    "highest_education": "HE Qualification",
    "imd_band": "10-20%",
    "num_of_prev_attempts": None,
    "studied_credits": 0,
    "module_total_assessments": None,
    "course_length": 240,
}
VLE = [
    {"enrollment_id": 32603, "date": -1, "sum_click": 0, "activity_type": "other"},
    {"enrollment_id": 32603, "date": 60, "sum_click": 17, "activity_type": "quiz"},
]
ASSESSMENTS = [
    {
        "enrollment_id": 32603,
        "date_submitted": 30,
        "score": None,
        "assessment_type": "TMA",
        "date": None,
    },
    {
        "enrollment_id": 32603,
        "date_submitted": 60,
        "score": Decimal("39.5"),
        "assessment_type": "CMA",
        "date": Decimal("55.5"),
    },
]


class RecordingConnection:
    def __init__(self, results=(), fail_write=None):
        self.results = iter(results)
        self.events = []
        self.fail_write = fail_write

    @contextmanager
    def connect(self):
        self.events.append("connection enter")
        try:
            yield self
        finally:
            self.events.append("connection close")

    @contextmanager
    def cursor(self):
        self.events.append("cursor enter")
        try:
            yield self
        finally:
            self.events.append("cursor close")

    def execute(self, sql, params=None):
        params = {
            key: (
                {"adapter": "Json", "value": value.obj}
                if isinstance(value, Json)
                else value
            )
            for key, value in (params or {}).items()
        }
        self.events.append({"sql": " ".join(sql.split()), "params": params})
        if "INSERT INTO predictions" in sql and self.fail_write:
            raise self.fail_write

    def fetchone(self):
        self.events.append("fetchone")
        return next(self.results)

    def fetchall(self):
        self.events.append("fetchall")
        return next(self.results)

    def commit(self):
        self.events.append("commit")


def data_contract(monkeypatch):
    loaded = RecordingConnection([BASE, VLE, ASSESSMENTS])
    monkeypatch.setattr(student_data, "get_connection", loaded.connect)
    enrollment, request = student_data.build_student_prediction_request(
        2026, "BBB", "2013B", 0.6
    )
    saved = RecordingConnection()
    monkeypatch.setattr(student_data, "get_connection", saved.connect)
    student_data.save_prediction(enrollment, RESPONSE)

    seen = []

    class Predictor:
        def predict(self, request):
            seen.append(request.model_dump(mode="json"))
            return RESPONSE

    # Demo rows include future evidence; its Python filter must retain its boundary.
    future_vle = {**VLE[-1], "date": 61}
    future_assessment = {**ASSESSMENTS[-1], "date_submitted": 61}
    demo = RecordingConnection(
        [[BASE], VLE + [future_vle], ASSESSMENTS + [future_assessment]]
    )
    monkeypatch.setattr(admin_data, "get_connection", demo.connect)
    summary = admin_data.run_demo_predictions(Predictor(), limit=7)
    return {
        "enrollment": enrollment,
        "request": request.model_dump(mode="json"),
        "load_events": loaded.events,
        "save_events": saved.events,
        "demo_requests": seen,
        "demo_events": demo.events,
        "demo_summary": summary,
    }


def test_data_access_matches_baseline(monkeypatch):
    assert data_contract(monkeypatch) == json.loads(
        (FIXTURES / "data_contract.json").read_text()
    )


@pytest.mark.parametrize(
    "value,expected",
    [(None, 0), ("M", 1), ("m", 1), (" M ", 0), ("F", 0), ("unknown", 0)],
)
def test_gender_mapping(value, expected):
    assert student_data.gender_bin(value) == expected


@pytest.mark.parametrize(
    "value,expected", [(None, 0), ("Y", 1), ("y", 1), (" Y ", 0), ("N", 0)]
)
def test_disability_mapping(value, expected):
    assert student_data.disability_bin(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(None, 0), ("0-35", 0), ("35-55", 1), ("55<=", 2), (" 35-55", 0), ("unknown", 0)],
)
def test_age_mapping(value, expected):
    assert student_data.age_numeric(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0),
        ("No Formal quals", 0),
        ("Lower Than A Level", 1),
        ("A Level or Equivalent", 2),
        ("HE Qualification", 3),
        ("Post Graduate Qualification", 4),
        ("he qualification", 0),
    ],
)
def test_education_mapping(value, expected):
    assert student_data.edu_numeric(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 50),
        ("", 50),
        ("20", 50),
        (" 10-20% ", 15),
        ("bad-20", 50),
        ("10-20-30", 50),
        ("0-10%", 5),
    ],
)
def test_imd_mapping(value, expected):
    assert student_data.imd_numeric(value) == expected


def test_failed_student_write_closes_without_committing(monkeypatch):
    conn = RecordingConnection(fail_write=RuntimeError("write failed"))
    monkeypatch.setattr(student_data, "get_connection", conn.connect)
    with pytest.raises(RuntimeError, match="write failed"):
        student_data.save_prediction(32603, RESPONSE)
    assert "commit" not in conn.events
    assert conn.events[-2:] == ["cursor close", "connection close"]


def test_demo_failure_does_not_commit_partial_batch(monkeypatch):
    conn = RecordingConnection(
        [[BASE, {**BASE, "enrollment_id": 32604}], VLE, ASSESSMENTS]
    )
    monkeypatch.setattr(admin_data, "get_connection", conn.connect)

    class Predictor:
        calls = 0

        def predict(self, request):
            self.calls += 1
            if self.calls == 2:
                raise ValueError("second student failed")
            return RESPONSE

    with pytest.raises(ValueError, match="second student failed"):
        admin_data.run_demo_predictions(Predictor())
    assert (
        sum(
            isinstance(e, dict) and "INSERT INTO predictions" in e["sql"]
            for e in conn.events
        )
        == 1
    )
    assert "commit" not in conn.events
    assert conn.events[-2:] == ["cursor close", "connection close"]


def test_empty_demo_does_not_commit(monkeypatch):
    conn = RecordingConnection([[]])
    monkeypatch.setattr(admin_data, "get_connection", conn.connect)
    assert admin_data.run_demo_predictions(object()) == {
        "total_students": 0,
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "low_risk_count": 0,
        "results": [],
    }
    assert "commit" not in conn.events

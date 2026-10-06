"""Convert database evidence into model requests without querying or persisting data."""

from typing import Any, Mapping, Optional

from schemas import AssessmentSubmission, Demographics, PredictRequest, VLEEvent


def gender_bin(value: Optional[str]) -> int:
    return 1 if str(value).upper() == "M" else 0


def disability_bin(value: Optional[str]) -> int:
    return 1 if str(value).upper() == "Y" else 0


def age_numeric(value: Optional[str]) -> int:
    mapping = {
        "0-35": 0,
        "35-55": 1,
        "55<=": 2,
    }
    return mapping.get(str(value), 0)


def edu_numeric(value: Optional[str]) -> int:
    mapping = {
        "No Formal quals": 0,
        "Lower Than A Level": 1,
        "A Level or Equivalent": 2,
        "HE Qualification": 3,
        "Post Graduate Qualification": 4,
    }
    return mapping.get(str(value), 0)


def imd_numeric(value: Optional[str]) -> float:
    if value is None:
        return 50.0

    text = str(value).replace("%", "").strip()
    if "-" not in text:
        return 50.0

    low, high = text.split("-", 1)
    try:
        return (float(low) + float(high)) / 2
    except ValueError:
        return 50.0


def vle_event_from_row(row: Mapping[str, Any]) -> VLEEvent:
    return VLEEvent(
        date=row["date"],
        sum_click=row["sum_click"],
        activity_type=row["activity_type"],
    )


def assessment_from_row(row: Mapping[str, Any]) -> AssessmentSubmission:
    return AssessmentSubmission(
        date_submitted=row["date_submitted"],
        score=float(row["score"]) if row["score"] is not None else 0.0,
        assessment_type=row["assessment_type"],
        date=float(row["date"]) if row["date"] is not None else None,
    )


def request_from_row(
    row: Mapping[str, Any],
    vle_log: list[VLEEvent],
    assess_log: list[AssessmentSubmission],
    threshold: Optional[float] = None,
) -> PredictRequest:
    """Build a request from evidence already selected by the caller's cutoff rules."""
    return PredictRequest(
        day_of_course=row["day_of_course"],
        demographics=Demographics(
            code_module=row["code_module"],
            gender_bin=gender_bin(row["gender"]),
            disability_bin=disability_bin(row["disability"]),
            age_numeric=age_numeric(row["age_band"]),
            edu_numeric=edu_numeric(row["highest_education"]),
            imd_numeric=imd_numeric(row["imd_band"]),
            num_of_prev_attempts=row["num_of_prev_attempts"] or 0,
            studied_credits=row["studied_credits"] or 1,
            module_total_assessments=row["module_total_assessments"] or 1,
            course_length=row["course_length"],
        ),
        vle_log=vle_log,
        assess_log=assess_log,
        threshold=threshold,
    )

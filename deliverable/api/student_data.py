from typing import Optional

from psycopg.types.json import Json

from db import get_connection
from schemas import (
    AssessmentSubmission,
    Demographics,
    PredictRequest,
    PredictResponse,
    VLEEvent,
)


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


def build_student_prediction_request(
    id_student: int,
    code_module: Optional[str] = None,
    code_presentation: Optional[str] = None,
    threshold: Optional[float] = None,
) -> tuple[int, PredictRequest]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            filters = ["pbv.id_student = %(id_student)s"]
            params = {"id_student": id_student}

            if code_module:
                filters.append("pbv.code_module = %(code_module)s")
                params["code_module"] = code_module

            if code_presentation:
                filters.append("pbv.code_presentation = %(code_presentation)s")
                params["code_presentation"] = code_presentation

            cur.execute(
                f"""
                SELECT
                    pbv.enrollment_id,
                    pbv.id_student,
                    pbv.code_module,
                    pbv.code_presentation,
                    ac.current_day AS day_of_course,
                    pbv.gender,
                    pbv.disability,
                    pbv.age_band,
                    pbv.highest_education,
                    pbv.imd_band,
                    pbv.num_of_prev_attempts,
                    pbv.studied_credits,
                    pbv.module_total_assessments,
                    pbv.course_length
                FROM prediction_base_view pbv
                JOIN enrollments e
                    ON e.id = pbv.enrollment_id
                JOIN academic_clocks ac
                    ON ac.course_presentation_id = e.course_presentation_id
                WHERE {" AND ".join(filters)}
                ORDER BY pbv.enrollment_id
                LIMIT 1
                """,
                params,
            )
            base = cur.fetchone()

            if base is None:
                raise LookupError("No enrollment found for this student")

            cur.execute(
                """
                SELECT
                    sve.date,
                    sve.sum_click,
                    vs.activity_type
                FROM student_vle_events sve
                JOIN vle_sites vs
                    ON vs.id_site = sve.id_site
                WHERE sve.enrollment_id = %(enrollment_id)s
                  AND sve.date <= %(day_of_course)s
                ORDER BY sve.date
                """,
                {
                    "enrollment_id": base["enrollment_id"],
                    "day_of_course": base["day_of_course"],
                },
            )
            vle_log = [
                VLEEvent(
                    date=row["date"],
                    sum_click=row["sum_click"],
                    activity_type=row["activity_type"],
                )
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT
                    sa.date_submitted,
                    sa.score,
                    a.assessment_type,
                    a.date
                FROM student_assessments sa
                JOIN assessments a
                    ON a.id_assessment = sa.id_assessment
                WHERE sa.enrollment_id = %(enrollment_id)s
                  AND sa.date_submitted <= %(day_of_course)s
                ORDER BY sa.date_submitted
                """,
                {
                    "enrollment_id": base["enrollment_id"],
                    "day_of_course": base["day_of_course"],
                },
            )
            assess_log = [
                AssessmentSubmission(
                    date_submitted=row["date_submitted"],
                    score=float(row["score"]) if row["score"] is not None else 0.0,
                    assessment_type=row["assessment_type"],
                    date=float(row["date"]) if row["date"] is not None else None,
                )
                for row in cur.fetchall()
            ]

    req = PredictRequest(
        day_of_course=base["day_of_course"],
        demographics=Demographics(
            code_module=base["code_module"],
            gender_bin=gender_bin(base["gender"]),
            disability_bin=disability_bin(base["disability"]),
            age_numeric=age_numeric(base["age_band"]),
            edu_numeric=edu_numeric(base["highest_education"]),
            imd_numeric=imd_numeric(base["imd_band"]),
            num_of_prev_attempts=base["num_of_prev_attempts"] or 0,
            studied_credits=base["studied_credits"] or 1,
            module_total_assessments=base["module_total_assessments"] or 1,
            course_length=base["course_length"],
        ),
        vle_log=vle_log,
        assess_log=assess_log,
        threshold=threshold,
    )
    return base["enrollment_id"], req


def save_prediction(enrollment_id: int, response: PredictResponse) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO predictions (
                    enrollment_id,
                    day_of_course,
                    risk_probability,
                    risk_level,
                    at_risk,
                    threshold_used,
                    recommended_action,
                    explanation,
                    model_confidence,
                    data_completeness
                )
                VALUES (
                    %(enrollment_id)s,
                    %(day_of_course)s,
                    %(risk_probability)s,
                    %(risk_level)s,
                    %(at_risk)s,
                    %(threshold_used)s,
                    %(recommended_action)s,
                    %(explanation)s,
                    %(model_confidence)s,
                    %(data_completeness)s
                )
                ON CONFLICT (enrollment_id, day_of_course) DO UPDATE
                SET
                    risk_probability = EXCLUDED.risk_probability,
                    risk_level = EXCLUDED.risk_level,
                    at_risk = EXCLUDED.at_risk,
                    threshold_used = EXCLUDED.threshold_used,
                    recommended_action = EXCLUDED.recommended_action,
                    explanation = EXCLUDED.explanation,
                    model_confidence = EXCLUDED.model_confidence,
                    data_completeness = EXCLUDED.data_completeness,
                    created_at = NOW()
                """,
                {
                    "enrollment_id": enrollment_id,
                    "day_of_course": response.model_confidence.day_of_course,
                    "risk_probability": response.risk_probability,
                    "risk_level": response.risk_level.value,
                    "at_risk": bool(response.at_risk),
                    "threshold_used": response.threshold_used,
                    "recommended_action": response.recommended_action,
                    "explanation": Json(response.explanation),
                    "model_confidence": Json(response.model_confidence.model_dump()),
                    "data_completeness": Json(response.data_completeness.model_dump()),
                },
            )
        conn.commit()

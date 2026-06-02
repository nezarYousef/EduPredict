from typing import Optional

from psycopg.types.json import Json

from db import get_connection
from predictor import EduPredictor
from schemas import AssessmentSubmission, Demographics, PredictRequest, PredictResponse, VLEEvent
from student_data import (
    age_numeric,
    disability_bin,
    edu_numeric,
    gender_bin,
    imd_numeric,
)


def list_clocks() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ac.id,
                    cp.code_module,
                    cp.code_presentation,
                    ac.current_day,
                    ac.max_day,
                    ac.is_running,
                    ac.speed_minutes_per_day,
                    ac.updated_at
                FROM academic_clocks ac
                JOIN course_presentations cp
                    ON cp.id = ac.course_presentation_id
                ORDER BY cp.code_module, cp.code_presentation
                """
            )
            return [dict(row) for row in cur.fetchall()]


def update_clock(
    code_module: str,
    code_presentation: str,
    current_day: Optional[int] = None,
    tick_days: int = 0,
    is_running: Optional[bool] = None,
) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ac.id, ac.current_day, ac.max_day
                FROM academic_clocks ac
                JOIN course_presentations cp
                    ON cp.id = ac.course_presentation_id
                WHERE cp.code_module = %(code_module)s
                  AND cp.code_presentation = %(code_presentation)s
                """,
                {
                    "code_module": code_module,
                    "code_presentation": code_presentation,
                },
            )
            clock = cur.fetchone()
            if clock is None:
                raise LookupError("Clock not found")

            next_day = clock["current_day"] if current_day is None else current_day
            next_day += tick_days
            next_day = max(0, min(next_day, clock["max_day"]))

            cur.execute(
                """
                UPDATE academic_clocks
                SET
                    current_day = %(current_day)s,
                    is_running = COALESCE(%(is_running)s, is_running),
                    last_tick_at = CASE
                        WHEN %(tick_days)s <> 0 THEN NOW()
                        ELSE last_tick_at
                    END,
                    updated_at = NOW()
                WHERE id = %(clock_id)s
                RETURNING
                    id,
                    current_day,
                    max_day,
                    is_running,
                    speed_minutes_per_day,
                    updated_at
                """,
                {
                    "clock_id": clock["id"],
                    "current_day": next_day,
                    "is_running": is_running,
                    "tick_days": tick_days,
                },
            )
            updated = dict(cur.fetchone())
        conn.commit()

    updated["code_module"] = code_module
    updated["code_presentation"] = code_presentation
    return updated


def demo_students() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    de.enrollment_id,
                    de.id_student,
                    cp.code_module,
                    cp.code_presentation
                FROM demo_enrollments de
                JOIN course_presentations cp
                    ON cp.id = de.course_presentation_id
                ORDER BY cp.code_module, cp.code_presentation, de.id_student
                """
            )
            return [dict(row) for row in cur.fetchall()]


def run_demo_predictions(predictor: EduPredictor, limit: int = 150) -> dict:
    results = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                FROM demo_enrollments de
                JOIN prediction_base_view pbv
                    ON pbv.enrollment_id = de.enrollment_id
                JOIN enrollments e
                    ON e.id = pbv.enrollment_id
                JOIN academic_clocks ac
                    ON ac.course_presentation_id = e.course_presentation_id
                ORDER BY pbv.enrollment_id
                LIMIT %(limit)s
                """,
                {"limit": limit},
            )
            students = [dict(row) for row in cur.fetchall()]

            enrollment_ids = [row["enrollment_id"] for row in students]
            if not enrollment_ids:
                return {
                    "total_students": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "results": [],
                }

            cur.execute(
                """
                SELECT
                    sve.enrollment_id,
                    sve.date,
                    sve.sum_click,
                    vs.activity_type
                FROM student_vle_events sve
                JOIN vle_sites vs
                    ON vs.id_site = sve.id_site
                WHERE sve.enrollment_id = ANY(%(enrollment_ids)s)
                ORDER BY sve.enrollment_id, sve.date
                """,
                {"enrollment_ids": enrollment_ids},
            )
            vle_by_enrollment: dict[int, list[VLEEvent]] = {}
            for row in cur.fetchall():
                vle_by_enrollment.setdefault(row["enrollment_id"], []).append(
                    VLEEvent(
                        date=row["date"],
                        sum_click=row["sum_click"],
                        activity_type=row["activity_type"],
                    )
                )

            cur.execute(
                """
                SELECT
                    sa.enrollment_id,
                    sa.date_submitted,
                    sa.score,
                    a.assessment_type,
                    a.date
                FROM student_assessments sa
                JOIN assessments a
                    ON a.id_assessment = sa.id_assessment
                WHERE sa.enrollment_id = ANY(%(enrollment_ids)s)
                ORDER BY sa.enrollment_id, sa.date_submitted
                """,
                {"enrollment_ids": enrollment_ids},
            )
            assessments_by_enrollment: dict[int, list[AssessmentSubmission]] = {}
            for row in cur.fetchall():
                assessments_by_enrollment.setdefault(row["enrollment_id"], []).append(
                    AssessmentSubmission(
                        date_submitted=row["date_submitted"],
                        score=float(row["score"]) if row["score"] is not None else 0.0,
                        assessment_type=row["assessment_type"],
                        date=float(row["date"]) if row["date"] is not None else None,
                    )
                )

            for student in students:
                req = _request_from_row(
                    student,
                    vle_by_enrollment.get(student["enrollment_id"], []),
                    assessments_by_enrollment.get(student["enrollment_id"], []),
                )
                response = predictor.predict(req)
                _save_prediction_with_cursor(cur, student["enrollment_id"], response)
                results.append(
                    {
                        "enrollment_id": student["enrollment_id"],
                        "id_student": student["id_student"],
                        "code_module": student["code_module"],
                        "code_presentation": student["code_presentation"],
                        "risk_probability": response.risk_probability,
                        "risk_level": response.risk_level.value,
                        "at_risk": response.at_risk,
                        "day_of_course": response.model_confidence.day_of_course,
                    }
                )
        conn.commit()

    return {
        "total_students": len(results),
        "high_risk_count": sum(1 for row in results if row["risk_level"] == "HIGH"),
        "medium_risk_count": sum(1 for row in results if row["risk_level"] == "MEDIUM"),
        "low_risk_count": sum(1 for row in results if row["risk_level"] == "LOW"),
        "results": sorted(results, key=lambda row: row["risk_probability"], reverse=True),
    }


def _request_from_row(
    row: dict,
    vle_log: list[VLEEvent],
    assess_log: list[AssessmentSubmission],
) -> PredictRequest:
    day = row["day_of_course"]

    return PredictRequest(
        day_of_course=day,
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
        vle_log=[event for event in vle_log if event.date <= day],
        assess_log=[submission for submission in assess_log if submission.date_submitted <= day],
    )


def _save_prediction_with_cursor(cur, enrollment_id: int, response: PredictResponse) -> None:
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


def list_latest_risk_students(
    risk_level: Optional[str] = None,
    at_risk: Optional[bool] = None,
    limit: int = 50,
) -> list[dict]:
    filters = []
    params = {"limit": limit}

    if risk_level:
        filters.append("p.risk_level = %(risk_level)s")
        params["risk_level"] = risk_level.upper()

    if at_risk is not None:
        filters.append("p.at_risk = %(at_risk)s")
        params["at_risk"] = at_risk

    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH latest AS (
                    SELECT DISTINCT ON (p.enrollment_id)
                        p.*
                    FROM predictions p
                    ORDER BY p.enrollment_id, p.day_of_course DESC, p.created_at DESC
                )
                SELECT
                    p.enrollment_id,
                    e.id_student,
                    cp.code_module,
                    cp.code_presentation,
                    p.day_of_course,
                    p.risk_probability,
                    p.risk_level,
                    p.at_risk,
                    p.recommended_action,
                    p.explanation,
                    p.created_at
                FROM latest p
                JOIN enrollments e
                    ON e.id = p.enrollment_id
                JOIN course_presentations cp
                    ON cp.id = e.course_presentation_id
                {where_clause}
                ORDER BY p.risk_probability DESC, p.created_at DESC
                LIMIT %(limit)s
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]

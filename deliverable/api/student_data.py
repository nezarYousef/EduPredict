from typing import Optional

from db import get_connection

# Keep the existing conversion imports available to callers of student_data.
from prediction_inputs import (
    age_numeric,
    assessment_from_row,
    disability_bin,
    edu_numeric,
    gender_bin,
    imd_numeric,
    request_from_row,
    vle_event_from_row,
)
from prediction_store import save_prediction_with_cursor
from schemas import PredictRequest, PredictResponse


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
            vle_log = [vle_event_from_row(row) for row in cur.fetchall()]

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
                ORDER BY sa.date_submitted, sa.id
                """,
                {
                    "enrollment_id": base["enrollment_id"],
                    "day_of_course": base["day_of_course"],
                },
            )
            assess_log = [assessment_from_row(row) for row in cur.fetchall()]

    req = request_from_row(base, vle_log, assess_log, threshold)
    return base["enrollment_id"], req


def next_assessment_due_date(enrollment_id: int, assessment_type: str) -> Optional[int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.date
                FROM assessments a
                JOIN enrollments e ON e.course_presentation_id = a.course_presentation_id
                WHERE e.id = %(enrollment_id)s
                  AND a.assessment_type = %(assessment_type)s
                  AND NOT EXISTS (
                    SELECT 1 FROM student_assessments sa
                    WHERE sa.enrollment_id = e.id AND sa.id_assessment = a.id_assessment
                  )
                ORDER BY a.date NULLS LAST, a.id_assessment
                LIMIT 1
                """,
                {"enrollment_id": enrollment_id, "assessment_type": assessment_type},
            )
            row = cur.fetchone()
    return row["date"] if row else None


def save_prediction(enrollment_id: int, response: PredictResponse) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            save_prediction_with_cursor(cur, enrollment_id, response)
        conn.commit()

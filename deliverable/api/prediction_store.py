"""Shared prediction persistence with caller-owned transaction boundaries."""

from psycopg import Cursor
from psycopg.types.json import Json

from schemas import PredictResponse


def save_prediction_with_cursor(
    cur: Cursor, enrollment_id: int, response: PredictResponse
) -> None:
    """Upsert one result; the caller owns the cursor, connection and transaction."""
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

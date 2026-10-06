"""HTTP authentication and sanitized error mapping shared by API routes."""

import logging
import os
from typing import Optional

from fastapi import Header, HTTPException
import psycopg

# Retain the existing logger name for operational log consumers.
logger = logging.getLogger("main")


def service_error(
    stage: str, error: Exception, *, database: bool = False
) -> HTTPException:
    # Exception messages can contain connection strings, SQL, or student data.
    logger.error(
        "EduPredict %s failed: %s (sqlstate=%s)",
        stage,
        type(error).__name__,
        getattr(error, "sqlstate", None),
    )
    if database and isinstance(error, (psycopg.Error, OSError, RuntimeError)):
        return HTTPException(
            status_code=503,
            detail="Prediction data service is temporarily unavailable.",
        )
    return HTTPException(
        status_code=500, detail="Prediction service is temporarily unavailable."
    )


def verify_admin_key(x_admin_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Invalid admin key")

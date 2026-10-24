"""Explicit, default-deny boundary for persistent academic database mutations."""

import os

from fastapi import HTTPException


def require_database_writes() -> None:
    if os.getenv("EDUPREDICT_ALLOW_DATABASE_WRITES", "").strip().lower() != "true":
        raise HTTPException(status_code=403, detail="Database writes are disabled.")

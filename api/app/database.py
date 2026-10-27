"""Backward-compatible database module.

New code should import from app.core.database.
"""

from app.core.database import DATABASE_URL, SessionLocal, engine, get_db

__all__ = ["DATABASE_URL", "SessionLocal", "engine", "get_db"]

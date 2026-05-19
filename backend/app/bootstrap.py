"""Database bootstrap helpers for deployed environments."""

import os
from pathlib import Path

from sqlalchemy import text

from app.db import engine


def _sql_dir() -> Path:
    configured = os.getenv("DB_BOOTSTRAP_DIR")
    if configured:
        return Path(configured)

    docker_path = Path("/app/db")
    if docker_path.exists():
        return docker_path

    return Path(__file__).resolve().parents[2] / "db"


def _statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def _execute_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8-sig")
    with engine.begin() as connection:
        for statement in _statements(sql):
            connection.execute(text(statement))


def bootstrap_database() -> None:
    """Create required schema, and optionally seed demo doctors for the UI."""
    sql_dir = _sql_dir()
    init_sql = sql_dir / "init.sql"
    if init_sql.exists():
        _execute_sql_file(init_sql)

    seed_enabled = os.getenv("DB_SEED_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
    seed_sql = sql_dir / "seed.sql"
    if not seed_enabled or not seed_sql.exists():
        return

    with engine.begin() as connection:
        doctor_count = connection.execute(text("SELECT COUNT(*) FROM doctors")).scalar_one()

    if doctor_count == 0:
        _execute_sql_file(seed_sql)

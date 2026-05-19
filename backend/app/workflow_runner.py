"""Helpers to run LangGraph workflows from API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.workflows.appointment_workflow import appointment_workflow


def _coerce_datetime(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def run_appointment_workflow(
    db: Session,
    *,
    user_input: str,
    extracted_entities: dict[str, Any],
    user_confirmed: bool,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "user_input": user_input,
        "extracted_entities": dict(extracted_entities or {}),
        "user_confirmed": user_confirmed,
        "db_session": db,
    }

    for dt_key in ["scheduled_start", "scheduled_end"]:
        if dt_key in state["extracted_entities"]:
            state["extracted_entities"][dt_key] = _coerce_datetime(state["extracted_entities"][dt_key])

    result = appointment_workflow.invoke(state)
    result.pop("db_session", None)
    return result

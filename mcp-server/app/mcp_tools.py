"""MCP tool registrations for MedVoice Scheduler."""

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.db import SessionLocal
from app.services import (
    book_appointment_service,
    check_availability_service,
    get_clinic_policy_service,
    get_patient_appointments_service,
    reschedule_appointment_service,
    search_doctor_or_department_service,
    verify_patient_service,
)

mcp_server = FastMCP("medvoice-scheduler-mcp")


def _parse_datetime(value: str) -> datetime:
    # Supports ISO 8601 timestamps like 2026-05-19T10:00:00+03:00
    return datetime.fromisoformat(value)


@mcp_server.tool(
    name="verify_patient",
    description="Verify patient identity by patient_code and/or phone with optional date_of_birth validation.",
)
def verify_patient(patient_code: str | None = None, phone: str | None = None, date_of_birth: str | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        return verify_patient_service(
            db,
            patient_code=patient_code,
            phone=phone,
            date_of_birth=date_of_birth,
        )


@mcp_server.tool(
    name="get_patient_appointments",
    description="Fetch appointments for a patient by patient_id or patient_code.",
)
def get_patient_appointments(patient_id: int | None = None, patient_code: str | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        return get_patient_appointments_service(db, patient_id=patient_id, patient_code=patient_code)


@mcp_server.tool(
    name="check_availability",
    description="Check whether a doctor is available in a requested time window.",
)
def check_availability(
    doctor_id: int,
    scheduled_start: str,
    scheduled_end: str,
    exclude_appointment_code: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        return check_availability_service(
            db,
            doctor_id=doctor_id,
            scheduled_start=_parse_datetime(scheduled_start),
            scheduled_end=_parse_datetime(scheduled_end),
            exclude_appointment_code=exclude_appointment_code,
        )


@mcp_server.tool(
    name="book_appointment",
    description="Book an appointment. This tool will not write unless confirmation=true.",
)
def book_appointment(
    patient_id: int,
    doctor_id: int,
    scheduled_start: str,
    scheduled_end: str,
    confirmation: bool,
    visit_type: str = "in_person",
    reason: str | None = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        return book_appointment_service(
            db,
            patient_id=patient_id,
            doctor_id=doctor_id,
            scheduled_start=_parse_datetime(scheduled_start),
            scheduled_end=_parse_datetime(scheduled_end),
            visit_type=visit_type,
            reason=reason,
            confirmation=confirmation,
        )


@mcp_server.tool(
    name="reschedule_appointment",
    description="Reschedule an appointment. This tool will not write unless confirmation=true.",
)
def reschedule_appointment(
    appointment_code: str,
    scheduled_start: str,
    scheduled_end: str,
    confirmation: bool,
) -> dict[str, Any]:
    with SessionLocal() as db:
        return reschedule_appointment_service(
            db,
            appointment_code=appointment_code,
            scheduled_start=_parse_datetime(scheduled_start),
            scheduled_end=_parse_datetime(scheduled_end),
            confirmation=confirmation,
        )


@mcp_server.tool(
    name="search_doctor_or_department",
    description="Search doctors by free-text query and/or department (specialty).",
)
def search_doctor_or_department(query: str | None = None, department: str | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        return search_doctor_or_department_service(db, query=query, department=department)


@mcp_server.tool(
    name="get_clinic_policy",
    description="Return clinic policy text for a topic such as booking, rescheduling, cancellation, or privacy.",
)
def get_clinic_policy(topic: str | None = None) -> dict[str, Any]:
    return get_clinic_policy_service(topic)

"""Service functions used by MCP tools."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Appointment, Doctor, Patient


def _normalize_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def verify_patient_service(
    db: Session,
    *,
    patient_code: str | None = None,
    phone: str | None = None,
    date_of_birth: str | None = None,
) -> dict:
    if not patient_code and not phone:
        return {"verified": False, "patient": None}

    filters = []
    if patient_code:
        filters.append(Patient.patient_code == patient_code)
    if phone:
        filters.append(Patient.phone == phone)

    patient = db.execute(select(Patient).where(and_(*filters))).scalars().first()
    if patient is None:
        return {"verified": False, "patient": None}

    if date_of_birth:
        expected = date.fromisoformat(date_of_birth)
        if patient.date_of_birth != expected:
            return {"verified": False, "patient": None}

    return {
        "verified": True,
        "patient": {
            "id": patient.id,
            "patient_code": patient.patient_code,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "phone": patient.phone,
            "email": patient.email,
        },
    }


def get_patient_appointments_service(
    db: Session,
    *,
    patient_id: int | None = None,
    patient_code: str | None = None,
) -> dict:
    resolved_patient_id = patient_id
    if resolved_patient_id is None and patient_code:
        patient = db.execute(select(Patient).where(Patient.patient_code == patient_code)).scalars().first()
        if not patient:
            return {"appointments": []}
        resolved_patient_id = patient.id

    if resolved_patient_id is None:
        return {"appointments": []}

    appts = (
        db.execute(
            select(Appointment)
            .where(Appointment.patient_id == resolved_patient_id)
            .order_by(Appointment.scheduled_start.asc())
        )
        .scalars()
        .all()
    )

    return {
        "appointments": [
            {
                "appointment_code": a.appointment_code,
                "patient_id": a.patient_id,
                "doctor_id": a.doctor_id,
                "scheduled_start": a.scheduled_start.isoformat(),
                "scheduled_end": a.scheduled_end.isoformat(),
                "status": a.status,
                "visit_type": a.visit_type,
                "reason": a.reason,
            }
            for a in appts
        ]
    }


def check_availability_service(
    db: Session,
    *,
    doctor_id: int,
    scheduled_start: datetime,
    scheduled_end: datetime,
    exclude_appointment_code: str | None = None,
) -> dict:
    start = _normalize_dt(scheduled_start)
    end = _normalize_dt(scheduled_end)

    if end <= start:
        return {"available": False, "conflicting_appointment_codes": [], "message": "Invalid time range."}

    stmt = (
        select(Appointment)
        .where(Appointment.doctor_id == doctor_id)
        .where(Appointment.status.in_(["scheduled", "confirmed"]))
        .where(Appointment.scheduled_start < end)
        .where(Appointment.scheduled_end > start)
    )

    conflicts = db.execute(stmt).scalars().all()
    conflict_codes = [a.appointment_code for a in conflicts if a.appointment_code != exclude_appointment_code]
    return {
        "available": len(conflict_codes) == 0,
        "conflicting_appointment_codes": conflict_codes,
        "message": "Available" if len(conflict_codes) == 0 else "Conflicting appointments found.",
    }


def book_appointment_service(
    db: Session,
    *,
    patient_id: int,
    doctor_id: int,
    scheduled_start: datetime,
    scheduled_end: datetime,
    visit_type: str = "in_person",
    reason: str | None = None,
    confirmation: bool = False,
) -> dict:
    if not confirmation:
        return {"success": False, "message": "Booking requires confirmation=true.", "appointment": None}

    patient = db.get(Patient, patient_id)
    doctor = db.get(Doctor, doctor_id)
    if not patient or not doctor:
        return {"success": False, "message": "Patient or doctor not found.", "appointment": None}

    availability = check_availability_service(
        db,
        doctor_id=doctor_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    if not availability["available"]:
        return {"success": False, "message": availability["message"], "appointment": None}

    appt = Appointment(
        appointment_code=f"APT-{uuid4().hex[:8].upper()}",
        patient_id=patient_id,
        doctor_id=doctor_id,
        scheduled_start=_normalize_dt(scheduled_start),
        scheduled_end=_normalize_dt(scheduled_end),
        status="confirmed",
        visit_type=visit_type,
        reason=reason,
        created_by="mcp",
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    return {
        "success": True,
        "message": "Appointment booked successfully.",
        "appointment": {
            "appointment_code": appt.appointment_code,
            "patient_id": appt.patient_id,
            "doctor_id": appt.doctor_id,
            "scheduled_start": appt.scheduled_start.isoformat(),
            "scheduled_end": appt.scheduled_end.isoformat(),
            "status": appt.status,
            "visit_type": appt.visit_type,
            "reason": appt.reason,
        },
    }


def reschedule_appointment_service(
    db: Session,
    *,
    appointment_code: str,
    scheduled_start: datetime,
    scheduled_end: datetime,
    confirmation: bool = False,
) -> dict:
    if not confirmation:
        return {"success": False, "message": "Rescheduling requires confirmation=true.", "appointment": None}

    appt = db.execute(select(Appointment).where(Appointment.appointment_code == appointment_code)).scalars().first()
    if not appt:
        return {"success": False, "message": "Appointment not found.", "appointment": None}

    availability = check_availability_service(
        db,
        doctor_id=appt.doctor_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        exclude_appointment_code=appointment_code,
    )
    if not availability["available"]:
        return {"success": False, "message": availability["message"], "appointment": None}

    appt.scheduled_start = _normalize_dt(scheduled_start)
    appt.scheduled_end = _normalize_dt(scheduled_end)
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)

    return {
        "success": True,
        "message": "Appointment rescheduled successfully.",
        "appointment": {
            "appointment_code": appt.appointment_code,
            "patient_id": appt.patient_id,
            "doctor_id": appt.doctor_id,
            "scheduled_start": appt.scheduled_start.isoformat(),
            "scheduled_end": appt.scheduled_end.isoformat(),
            "status": appt.status,
            "visit_type": appt.visit_type,
            "reason": appt.reason,
        },
    }


def search_doctor_or_department_service(
    db: Session,
    *,
    query: str | None = None,
    department: str | None = None,
) -> dict:
    stmt = select(Doctor)

    if query:
        q = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Doctor.first_name).like(q),
                func.lower(Doctor.last_name).like(q),
                func.lower(Doctor.specialty).like(q),
                func.lower(Doctor.clinic_location).like(q),
            )
        )

    if department:
        stmt = stmt.where(func.lower(Doctor.specialty) == department.lower())

    doctors = db.execute(stmt.order_by(Doctor.last_name.asc())).scalars().all()
    return {
        "results": [
            {
                "id": d.id,
                "doctor_code": d.doctor_code,
                "first_name": d.first_name,
                "last_name": d.last_name,
                "specialty": d.specialty,
                "clinic_location": d.clinic_location,
            }
            for d in doctors
        ]
    }


def get_clinic_policy_service(topic: str | None = None) -> dict:
    policies = {
        "booking": "Appointments require explicit patient confirmation before booking.",
        "rescheduling": "Rescheduling requires explicit patient confirmation and an available timeslot.",
        "cancellation": "Cancellations should be requested at least 24 hours before scheduled time when possible.",
        "privacy": "Patient data must be handled according to clinic privacy and data-protection policies.",
        "default": "Clinic policy: verify patient identity, confirm appointment intent, and document all changes.",
    }

    key = (topic or "default").strip().lower()
    return {
        "topic": key,
        "policy": policies.get(key, policies["default"]),
    }

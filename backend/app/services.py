"""Domain services for scheduling flows.

These functions are designed to be easy to unit test by injecting a SQLAlchemy session.
"""

from datetime import date, datetime, timezone
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Appointment, ConversationLog, Doctor, Patient

ACTIVE_APPOINTMENT_STATUSES = ("scheduled", "confirmed", "confirmed_coming", "rescheduled")


def normalize_phone_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")
    prefix = "+" if cleaned.startswith("+") else ""
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        return None
    return f"{prefix}{digits}"


def identify_or_create_patient(
    db: Session,
    *,
    full_name: str,
    preferred_language: str | None = "en",
    phone: str | None = None,
    email: str | None = None,
) -> dict:
    """Find existing patient by name (and optional phone) or create a new one."""
    normalized = " ".join((full_name or "").strip().split())
    if not normalized:
        raise ValueError("full_name is required")

    parts = normalized.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else "Visitor"

    existing = None
    if phone:
        phone_stmt = select(Patient).where(Patient.phone == phone)
        existing = db.execute(phone_stmt).scalars().first()

    stmt = select(Patient).where(
        func.lower(Patient.first_name) == first_name.lower(),
        func.lower(Patient.last_name) == last_name.lower(),
    )

    if existing is None:
        existing = db.execute(stmt).scalars().first()

    if existing:
        changed = False
        if phone and not existing.phone:
            existing.phone = phone
            changed = True
        if email and not existing.email:
            existing.email = email
            changed = True
        if preferred_language and existing.preferred_language != preferred_language.lower():
            existing.preferred_language = preferred_language.lower()
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)

        return {
            "created": False,
            "patient": {
                "id": existing.id,
                "patient_code": existing.patient_code,
                "first_name": existing.first_name,
                "last_name": existing.last_name,
                "date_of_birth": existing.date_of_birth.isoformat() if existing.date_of_birth else None,
                "phone": existing.phone,
                "email": existing.email,
            },
        }

    patient_code = f"PAT-{uuid.uuid4().hex[:8].upper()}"
    created = Patient(
        patient_code=patient_code,
        first_name=first_name,
        last_name=last_name,
        preferred_language=(preferred_language or "en").lower(),
        phone=phone,
        email=email,
    )
    db.add(created)
    db.commit()
    db.refresh(created)

    return {
        "created": True,
        "patient": {
            "id": created.id,
            "patient_code": created.patient_code,
            "first_name": created.first_name,
            "last_name": created.last_name,
            "date_of_birth": created.date_of_birth.isoformat() if created.date_of_birth else None,
            "phone": created.phone,
            "email": created.email,
        },
    }


def _normalize_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _appointment_to_dict(appt: Appointment) -> dict:
    return {
        "appointment_code": appt.appointment_code,
        "patient_id": appt.patient_id,
        "doctor_id": appt.doctor_id,
        "scheduled_start": appt.scheduled_start,
        "scheduled_end": appt.scheduled_end,
        "status": appt.status,
        "visit_type": appt.visit_type,
        "reason": appt.reason,
    }


def _appointment_detail_to_dict(appt: Appointment, patient: Patient, doctor: Doctor) -> dict:
    return {
        "appointment": _appointment_to_dict(appt),
        "patient": {
            "id": patient.id,
            "patient_code": patient.patient_code,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "email": patient.email,
        },
        "doctor": {
            "id": doctor.id,
            "doctor_code": doctor.doctor_code,
            "first_name": doctor.first_name,
            "last_name": doctor.last_name,
            "specialty": doctor.specialty,
            "clinic_location": doctor.clinic_location,
        },
    }


def verify_patient(
    db: Session,
    patient_code: str | None = None,
    phone: str | None = None,
    date_of_birth: str | None = None,
) -> dict:
    """Verify a patient by code and optional phone/dob attributes."""
    if not patient_code and not phone:
        return {"verified": False, "patient": None}

    filters = []
    if patient_code:
        filters.append(Patient.patient_code == patient_code)
    if phone:
        filters.append(Patient.phone == phone)

    stmt = select(Patient).where(and_(*filters))
    patient = db.execute(stmt).scalars().first()

    if patient is None:
        return {"verified": False, "patient": None}

    if date_of_birth:
        expected_dob = date.fromisoformat(date_of_birth)
        if patient.date_of_birth != expected_dob:
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


def search_doctors(db: Session, query: str | None = None, department: str | None = None) -> list[dict]:
    """Search doctors by free-text query and/or department(specialty)."""
    stmt = select(Doctor)
    normalized_query = (query or "").strip()
    normalized_department = (department or "").strip()

    specialty_aliases = {
        "dermatologist": "dermatology",
        "skin doctor": "dermatology",
        "skin specialist": "dermatology",
        "skin clinic": "dermatology",
        "skin problem": "dermatology",
        "general medicine": "family medicine",
        "general doctor": "family medicine",
        "general physician": "family medicine",
        "gp": "family medicine",
        "primary care": "family medicine",
        "family doctor": "family medicine",
        "cardiologist": "cardiology",
        "heart doctor": "cardiology",
        "heart specialist": "cardiology",
        "heart clinic": "cardiology",
        "blood pressure": "cardiology",
        "hypertension": "cardiology",
        "pediatrician": "pediatrics",
        "child doctor": "pediatrics",
        "children doctor": "pediatrics",
    }
    lookup_text = f"{normalized_query} {normalized_department}".lower()
    matched_specialty_alias = False
    for phrase, specialty in specialty_aliases.items():
        if phrase in lookup_text:
            normalized_department = specialty
            matched_specialty_alias = True
            break
    if matched_specialty_alias:
        normalized_query = ""

    if normalized_query:
        like_query = f"%{normalized_query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Doctor.first_name).like(like_query),
                func.lower(Doctor.last_name).like(like_query),
                func.lower(Doctor.specialty).like(like_query),
                func.lower(Doctor.clinic_location).like(like_query),
            )
        )

    if normalized_department:
        stmt = stmt.where(func.lower(Doctor.specialty) == normalized_department.lower())

    doctors = db.execute(stmt.order_by(Doctor.last_name.asc())).scalars().all()
    return [
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


def check_appointment_availability(db: Session, doctor_id: int, scheduled_start: datetime, scheduled_end: datetime) -> dict:
    """Check if a doctor is free in the requested time window."""
    start = _normalize_dt(scheduled_start)
    end = _normalize_dt(scheduled_end)

    if end <= start:
        return {"available": False, "conflicting_appointment_codes": []}

    overlap_stmt = (
        select(Appointment)
        .where(Appointment.doctor_id == doctor_id)
        .where(Appointment.status.in_(["scheduled", "confirmed"]))
        .where(Appointment.scheduled_start < end)
        .where(Appointment.scheduled_end > start)
    )

    conflicts = db.execute(overlap_stmt).scalars().all()
    return {
        "available": len(conflicts) == 0,
        "conflicting_appointment_codes": [c.appointment_code for c in conflicts],
    }


def book_appointment(
    db: Session,
    *,
    patient_id: int,
    doctor_id: int,
    scheduled_start: datetime,
    scheduled_end: datetime,
    visit_type: str,
    reason: str | None,
    confirmation: bool,
) -> dict:
    """Book a new appointment, but only when confirmation=True."""
    if not confirmation:
        return {"success": False, "appointment": None, "message": "Booking requires confirmation=true."}

    patient = db.get(Patient, patient_id)
    doctor = db.get(Doctor, doctor_id)
    if patient is None or doctor is None:
        return {"success": False, "appointment": None, "message": "Patient or doctor not found."}

    availability = check_appointment_availability(db, doctor_id, scheduled_start, scheduled_end)
    if not availability["available"]:
        return {
            "success": False,
            "appointment": None,
            "message": "Requested slot is unavailable.",
        }

    appointment_code = f"APT-{uuid.uuid4().hex[:8].upper()}"
    appt = Appointment(
        appointment_code=appointment_code,
        patient_id=patient_id,
        doctor_id=doctor_id,
        scheduled_start=_normalize_dt(scheduled_start),
        scheduled_end=_normalize_dt(scheduled_end),
        status="confirmed",
        visit_type=visit_type,
        reason=reason,
        created_by="api",
    )
    db.add(appt)
    db.flush()

    log = ConversationLog(
        conversation_id=str(uuid.uuid4()),
        appointment_id=appt.id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        role="system",
        channel="chat",
        message_text="Appointment booked via API",
        language="en",
        sentiment_score=None,
        metadata_json={"event": "appointment_booked"},
    )
    db.add(log)
    db.commit()
    db.refresh(appt)

    return {
        "success": True,
        "appointment": _appointment_to_dict(appt),
        "message": "Appointment booked successfully.",
    }


def reschedule_appointment(
    db: Session,
    *,
    appointment_code: str,
    scheduled_start: datetime,
    scheduled_end: datetime,
    confirmation: bool,
) -> dict:
    """Reschedule an existing appointment, but only when confirmation=True."""
    if not confirmation:
        return {
            "success": False,
            "appointment": None,
            "message": "Rescheduling requires confirmation=true.",
        }

    appt_stmt = select(Appointment).where(Appointment.appointment_code == appointment_code)
    appt = db.execute(appt_stmt).scalars().first()
    if appt is None:
        return {"success": False, "appointment": None, "message": "Appointment not found."}

    availability = check_appointment_availability(db, appt.doctor_id, scheduled_start, scheduled_end)
    other_conflicts = [code for code in availability["conflicting_appointment_codes"] if code != appointment_code]
    if other_conflicts:
        return {
            "success": False,
            "appointment": None,
            "message": "Requested new slot is unavailable.",
        }

    appt.scheduled_start = _normalize_dt(scheduled_start)
    appt.scheduled_end = _normalize_dt(scheduled_end)
    appt.status = "confirmed"
    db.flush()

    log = ConversationLog(
        conversation_id=str(uuid.uuid4()),
        appointment_id=appt.id,
        patient_id=appt.patient_id,
        doctor_id=appt.doctor_id,
        role="system",
        channel="chat",
        message_text="Appointment rescheduled via API",
        language="en",
        sentiment_score=None,
        metadata_json={"event": "appointment_rescheduled"},
    )
    db.add(log)
    db.commit()
    db.refresh(appt)

    return {
        "success": True,
        "appointment": _appointment_to_dict(appt),
        "message": "Appointment rescheduled successfully.",
    }


def lookup_patient_by_phone(db: Session, *, phone: str) -> dict:
    normalized_phone = normalize_phone_number(phone)
    if not normalized_phone:
        return {
            "found": False,
            "patient": None,
            "active_appointments": [],
            "message": "A valid phone number is required.",
        }

    patient = db.execute(select(Patient).where(Patient.phone == normalized_phone)).scalars().first()
    if patient is None:
        return {
            "found": False,
            "patient": None,
            "active_appointments": [],
            "message": "No patient was found with this phone number.",
        }

    rows = db.execute(
        select(Appointment, Doctor)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .where(Appointment.patient_id == patient.id)
        .where(Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES))
        .where(Appointment.scheduled_start >= datetime.now(timezone.utc))
        .order_by(Appointment.scheduled_start.asc())
    ).all()

    return {
        "found": True,
        "patient": {
            "id": patient.id,
            "patient_code": patient.patient_code,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "email": patient.email,
        },
        "active_appointments": [
            _appointment_detail_to_dict(appt, patient, doctor)
            for appt, doctor in rows
        ],
        "message": "Patient found." if rows else "Patient found with no active future appointments.",
    }


def cancel_appointment(
    db: Session,
    *,
    appointment_code: str,
    confirmation: bool,
) -> dict:
    """Cancel an existing appointment, but only when confirmation=True."""
    if not confirmation:
        return {
            "success": False,
            "appointment": None,
            "message": "Cancellation requires confirmation=true.",
        }

    appt_stmt = select(Appointment).where(Appointment.appointment_code == appointment_code)
    appt = db.execute(appt_stmt).scalars().first()
    if appt is None:
        return {"success": False, "appointment": None, "message": "Appointment not found."}

    appt.status = "cancelled"
    db.flush()

    log = ConversationLog(
        conversation_id=str(uuid.uuid4()),
        appointment_id=appt.id,
        patient_id=appt.patient_id,
        doctor_id=appt.doctor_id,
        role="system",
        channel="chat",
        message_text="Appointment cancelled via API",
        language="en",
        sentiment_score=None,
        metadata_json={"event": "appointment_cancelled"},
    )
    db.add(log)
    db.commit()
    db.refresh(appt)

    return {
        "success": True,
        "appointment": _appointment_to_dict(appt),
        "message": "Appointment cancelled successfully.",
    }

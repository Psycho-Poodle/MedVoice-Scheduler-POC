"""FastAPI routes for scheduling services."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.realtime import create_realtime_session
from app.schemas import (
    AvailabilityCheckRequest,
    AvailabilityCheckResponse,
    BookAppointmentRequest,
    BookAppointmentResponse,
    CancelAppointmentRequest,
    CancelAppointmentResponse,
    DoctorResponse,
    DoctorSearchRequest,
    PatientIdentifyRequest,
    PatientIdentifyResponse,
    PatientVerificationRequest,
    PatientVerificationResponse,
    RealtimeSessionRequest,
    RealtimeSessionResponse,
    RescheduleAppointmentRequest,
    RescheduleAppointmentResponse,
    RunAppointmentWorkflowRequest,
    RunAppointmentWorkflowResponse,
)
from app.services import (
    book_appointment,
    cancel_appointment,
    check_appointment_availability,
    identify_or_create_patient,
    reschedule_appointment,
    search_doctors,
    verify_patient,
)
from app.workflow_runner import run_appointment_workflow

router = APIRouter(tags=["scheduler"])


@router.post("/patients/verify", response_model=PatientVerificationResponse)
def verify_patient_route(payload: PatientVerificationRequest, db: Session = Depends(get_db)) -> PatientVerificationResponse:
    result = verify_patient(
        db,
        patient_code=payload.patient_code,
        phone=payload.phone,
        date_of_birth=payload.date_of_birth,
    )
    return PatientVerificationResponse(**result)


@router.post("/patients/identify-or-create", response_model=PatientIdentifyResponse)
def identify_or_create_patient_route(
    payload: PatientIdentifyRequest,
    db: Session = Depends(get_db),
) -> PatientIdentifyResponse:
    try:
        result = identify_or_create_patient(
            db,
            full_name=payload.full_name,
            preferred_language=payload.preferred_language,
            phone=payload.phone,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PatientIdentifyResponse(**result)


@router.post("/doctors/search", response_model=list[DoctorResponse])
def search_doctors_route(payload: DoctorSearchRequest, db: Session = Depends(get_db)) -> list[DoctorResponse]:
    results = search_doctors(db, query=payload.query, department=payload.department)
    return [DoctorResponse(**item) for item in results]


@router.post("/appointments/availability", response_model=AvailabilityCheckResponse)
def check_availability_route(
    payload: AvailabilityCheckRequest,
    db: Session = Depends(get_db),
) -> AvailabilityCheckResponse:
    result = check_appointment_availability(
        db,
        doctor_id=payload.doctor_id,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
    )
    return AvailabilityCheckResponse(**result)


@router.post("/appointments/book", response_model=BookAppointmentResponse)
def book_appointment_route(payload: BookAppointmentRequest, db: Session = Depends(get_db)) -> BookAppointmentResponse:
    if not payload.confirmation:
        raise HTTPException(status_code=400, detail="booking requires confirmation=true")

    result = book_appointment(
        db,
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        visit_type=payload.visit_type.value,
        reason=payload.reason,
        confirmation=payload.confirmation,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return BookAppointmentResponse(**result)


@router.post("/appointments/reschedule", response_model=RescheduleAppointmentResponse)
def reschedule_appointment_route(
    payload: RescheduleAppointmentRequest,
    db: Session = Depends(get_db),
) -> RescheduleAppointmentResponse:
    if not payload.confirmation:
        raise HTTPException(status_code=400, detail="rescheduling requires confirmation=true")

    result = reschedule_appointment(
        db,
        appointment_code=payload.appointment_code,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        confirmation=payload.confirmation,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return RescheduleAppointmentResponse(**result)


@router.post("/appointments/cancel", response_model=CancelAppointmentResponse)
def cancel_appointment_route(
    payload: CancelAppointmentRequest,
    db: Session = Depends(get_db),
) -> CancelAppointmentResponse:
    if not payload.confirmation:
        raise HTTPException(status_code=400, detail="cancellation requires confirmation=true")

    result = cancel_appointment(
        db,
        appointment_code=payload.appointment_code,
        confirmation=payload.confirmation,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return CancelAppointmentResponse(**result)


@router.post("/realtime/session", response_model=RealtimeSessionResponse)
async def create_realtime_session_route(payload: RealtimeSessionRequest) -> RealtimeSessionResponse:
    try:
        session = await create_realtime_session(user_id=payload.user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create realtime session: {exc}") from exc

    session_obj = session.get("session", {}) if isinstance(session, dict) else {}
    client_secret_obj = session_obj.get("client_secret") or {
        "value": session.get("value") if isinstance(session, dict) else None,
        "expires_at": session.get("expires_at") if isinstance(session, dict) else None,
    }
    output_voice = ((session_obj.get("audio") or {}).get("output") or {}).get("voice")

    return RealtimeSessionResponse(
        id=session_obj.get("id"),
        client_secret=client_secret_obj,
        expires_at=session.get("expires_at") if isinstance(session, dict) else None,
        model=session_obj.get("model"),
        modalities=session_obj.get("output_modalities"),
        voice=output_voice,
        raw=session,
    )


@router.post("/langgraph/appointment/run", response_model=RunAppointmentWorkflowResponse)
def run_appointment_workflow_route(
    payload: RunAppointmentWorkflowRequest,
    db: Session = Depends(get_db),
) -> RunAppointmentWorkflowResponse:
    result_state = run_appointment_workflow(
        db,
        user_input=payload.user_input,
        extracted_entities=payload.extracted_entities,
        user_confirmed=payload.user_confirmed,
    )
    return RunAppointmentWorkflowResponse(state=result_state)

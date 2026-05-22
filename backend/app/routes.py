"""FastAPI routes for scheduling services."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.gemini_live import GeminiLiveError, synthesize_assistant_speech, transcribe_user_audio
from app.realtime import create_realtime_session
from app.schemas import (
    AssistantSpeechRequest,
    AvailabilityCheckRequest,
    AvailabilityCheckResponse,
    BookAppointmentRequest,
    BookAppointmentResponse,
    CancelAppointmentRequest,
    CancelAppointmentResponse,
    ConfirmComingRequest,
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
    VapiCancelRequest,
    VapiReminderRunResponse,
    VapiRescheduleRequest,
    VapiToolResponse,
    VoiceTranscriptionRequest,
    VoiceTranscriptionResponse,
)
from app.services import (
    book_appointment,
    cancel_appointment,
    check_appointment_availability,
    confirm_appointment_coming,
    identify_or_create_patient,
    list_vapi_due_reminders,
    mark_vapi_call_started,
    reschedule_appointment,
    search_doctors,
    vapi_reschedule_appointment,
    verify_patient,
)
from app.vapi import VapiAPIError, VapiConfigError, create_outbound_call
from app.workflow_runner import run_appointment_workflow

router = APIRouter(tags=["scheduler"])


def _extract_vapi_tool_args(payload: dict) -> tuple[str | None, dict]:
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, dict):
        tool_call_list = message.get("toolCallList") or []
        if tool_call_list:
            tool_call = tool_call_list[0]
            return tool_call.get("name"), tool_call.get("parameters") or {}

    tool_calls = []
    if isinstance(message, dict):
        tool_calls = message.get("toolCalls") or message.get("tool_calls") or []
    if not tool_calls and isinstance(payload, dict):
        tool_calls = payload.get("toolCalls") or payload.get("tool_calls") or []
    if not tool_calls:
        return None, {}

    tool_call = tool_calls[0]
    function = tool_call.get("function") or {}
    name = function.get("name") or tool_call.get("name")
    args = function.get("arguments") or tool_call.get("arguments") or {}
    if isinstance(args, str):
        import json

        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args if isinstance(args, dict) else {}


def _extract_vapi_tool_call_id(payload: dict) -> str | None:
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, dict):
        tool_call_list = message.get("toolCallList") or []
        if tool_call_list:
            return tool_call_list[0].get("id")
        tool_with_list = message.get("toolWithToolCallList") or []
        if tool_with_list:
            return (tool_with_list[0].get("toolCall") or {}).get("id")
    tool_calls = payload.get("toolCalls") or payload.get("tool_calls") or []
    if tool_calls:
        return tool_calls[0].get("id")
    return None


def _parse_vapi_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        raise HTTPException(status_code=400, detail="scheduled_start is required")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def run_vapi_due_reminders(db: Session, *, limit: int = 20) -> dict:
    due = list_vapi_due_reminders(db, limit=limit)
    result = {"attempted": len(due), "started": 0, "errors": [], "calls": []}
    for item in due:
        appt = item["appointment"]
        patient = item["patient"]
        doctor = item["doctor"]
        patient_name = f"{patient['first_name']} {patient['last_name']}"
        doctor_name = f"Dr. {doctor['first_name']} {doctor['last_name']}"
        try:
            call = await create_outbound_call(
                phone_number=patient["phone"],
                appointment_code=appt["appointment_code"],
                patient_name=patient_name,
                doctor_name=doctor_name,
                scheduled_start=appt["scheduled_start"].isoformat(),
            )
            call_id = call.get("id") if isinstance(call, dict) else None
            mark_vapi_call_started(db, appointment_code=appt["appointment_code"], vapi_call_id=call_id)
            result["started"] += 1
            result["calls"].append({"appointment_code": appt["appointment_code"], "call_id": call_id})
        except (VapiAPIError, VapiConfigError, Exception) as exc:
            result["errors"].append(f"{appt['appointment_code']}: {exc}")
    return result


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


@router.get("/vapi/reminders/due")
def list_vapi_due_reminders_route(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_vapi_due_reminders(db, limit=limit)


@router.post("/vapi/reminders/run", response_model=VapiReminderRunResponse)
async def run_vapi_due_reminders_route(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> VapiReminderRunResponse:
    result = await run_vapi_due_reminders(db, limit=limit)
    return VapiReminderRunResponse(**result)


@router.post("/vapi/appointments/confirm-coming", response_model=VapiToolResponse)
def vapi_confirm_coming_route(
    payload: ConfirmComingRequest,
    db: Session = Depends(get_db),
) -> VapiToolResponse:
    result = confirm_appointment_coming(db, appointment_code=payload.appointment_code)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return VapiToolResponse(result=result)


@router.post("/vapi/appointments/reschedule", response_model=VapiToolResponse)
def vapi_reschedule_route(
    payload: VapiRescheduleRequest,
    db: Session = Depends(get_db),
) -> VapiToolResponse:
    result = vapi_reschedule_appointment(
        db,
        appointment_code=payload.appointment_code,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return VapiToolResponse(result=result)


@router.post("/vapi/appointments/cancel", response_model=VapiToolResponse)
def vapi_cancel_route(
    payload: VapiCancelRequest,
    db: Session = Depends(get_db),
) -> VapiToolResponse:
    result = cancel_appointment(db, appointment_code=payload.appointment_code, confirmation=True)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return VapiToolResponse(result=result)


@router.post("/vapi/tools", response_model=VapiToolResponse)
def vapi_tools_route(payload: dict, db: Session = Depends(get_db)) -> VapiToolResponse:
    tool_name, args = _extract_vapi_tool_args(payload)
    if tool_name == "confirm_coming":
        result = confirm_appointment_coming(db, appointment_code=str(args.get("appointment_code", "")))
    elif tool_name == "reschedule_appointment":
        scheduled_start = _parse_vapi_datetime(args.get("scheduled_start"))
        scheduled_end = _parse_vapi_datetime(args.get("scheduled_end")) if args.get("scheduled_end") else scheduled_start + timedelta(minutes=30)
        result = vapi_reschedule_appointment(
            db,
            appointment_code=str(args.get("appointment_code", "")),
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        )
    elif tool_name == "cancel_appointment":
        result = cancel_appointment(db, appointment_code=str(args.get("appointment_code", "")), confirmation=True)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported Vapi tool: {tool_name}")

    return VapiToolResponse(result=result)


@router.post("/vapi/tool-calls")
def vapi_tool_calls_route(payload: dict, db: Session = Depends(get_db)) -> dict:
    tool_name, args = _extract_vapi_tool_args(payload)
    tool_call_id = _extract_vapi_tool_call_id(payload)
    if tool_name == "confirm_coming":
        result = confirm_appointment_coming(db, appointment_code=str(args.get("appointment_code", "")))
    elif tool_name == "reschedule_appointment":
        scheduled_start = _parse_vapi_datetime(args.get("scheduled_start"))
        scheduled_end = _parse_vapi_datetime(args.get("scheduled_end")) if args.get("scheduled_end") else scheduled_start + timedelta(minutes=30)
        result = vapi_reschedule_appointment(
            db,
            appointment_code=str(args.get("appointment_code", "")),
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        )
    elif tool_name == "cancel_appointment":
        result = cancel_appointment(db, appointment_code=str(args.get("appointment_code", "")), confirmation=True)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported Vapi tool: {tool_name}")

    import json

    return {
        "results": [
            {
                "toolCallId": tool_call_id,
                "name": tool_name,
                "result": json.dumps(result, default=str),
            }
        ]
    }


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


@router.post("/realtime/speech")
async def synthesize_assistant_speech_route(payload: AssistantSpeechRequest) -> Response:
    try:
        audio = await synthesize_assistant_speech(text=payload.text, voice=payload.voice)
    except GeminiLiveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to synthesize assistant speech: {exc}") from exc

    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/realtime/transcribe", response_model=VoiceTranscriptionResponse)
async def transcribe_user_audio_route(payload: VoiceTranscriptionRequest) -> VoiceTranscriptionResponse:
    try:
        transcript = await transcribe_user_audio(audio_base64=payload.audio_base64, mime_type=payload.mime_type)
    except GeminiLiveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to transcribe voice input: {exc}") from exc

    return VoiceTranscriptionResponse(transcript=transcript)


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

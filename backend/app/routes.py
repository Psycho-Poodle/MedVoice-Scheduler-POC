"""FastAPI routes for scheduling services."""

from datetime import datetime
import json

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
    DoctorResponse,
    DoctorSearchRequest,
    PatientIdentifyRequest,
    PatientIdentifyResponse,
    PatientPhoneLookupRequest,
    PatientPhoneLookupResponse,
    PatientVerificationRequest,
    PatientVerificationResponse,
    RealtimeSessionRequest,
    RealtimeSessionResponse,
    RescheduleAppointmentRequest,
    RescheduleAppointmentResponse,
    RunAppointmentWorkflowRequest,
    RunAppointmentWorkflowResponse,
    VoiceTranscriptionRequest,
    VoiceTranscriptionResponse,
)
from app.services import (
    book_appointment,
    cancel_appointment,
    check_appointment_availability,
    database_summary,
    identify_or_create_patient,
    lookup_patient_by_phone,
    reschedule_appointment,
    search_doctors,
    verify_patient,
)
from app.workflow_runner import run_appointment_workflow

router = APIRouter(tags=["scheduler"])


def _extract_vapi_tool_calls(payload: dict) -> list[dict]:
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, dict):
        if isinstance(message.get("toolCallList"), list):
            return [
                {"id": item.get("id"), "name": item.get("name"), "arguments": item.get("parameters") or {}}
                for item in message["toolCallList"]
            ]
        if isinstance(message.get("toolCalls"), list):
            return message["toolCalls"]
        if isinstance(message.get("tool_calls"), list):
            return message["tool_calls"]
    if isinstance(payload.get("toolCalls"), list):
        return payload["toolCalls"]
    if isinstance(payload.get("tool_calls"), list):
        return payload["tool_calls"]
    if payload.get("name") or payload.get("function"):
        return [payload]
    return []


def _normalize_tool_call(tool_call: dict) -> tuple[str | None, str | None, dict]:
    function = tool_call.get("function") or {}
    name = function.get("name") or tool_call.get("name") or tool_call.get("toolName")
    tool_call_id = tool_call.get("id") or tool_call.get("toolCallId")
    args = function.get("arguments") or tool_call.get("arguments") or tool_call.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return tool_call_id, name, args if isinstance(args, dict) else {}


def _canonical_tool_name(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    normalized = "".join(ch if ch.isalnum() else "_" for ch in tool_name.strip().lower())
    normalized = "_".join(part for part in normalized.split("_") if part)
    aliases = {
        "lookup_patient": "lookup_patient_by_phone",
        "patient_lookup": "lookup_patient_by_phone",
        "phone_lookup": "lookup_patient_by_phone",
        "search_doctor": "search_doctors",
        "doctor_search": "search_doctors",
        "search_doctors": "search_doctors",
        "check_availability": "check_appointment_availability",
        "availability": "check_appointment_availability",
        "book": "book_appointment",
        "book_appointment": "book_appointment",
        "reschedule": "reschedule_appointment",
        "reschedule_appointment": "reschedule_appointment",
        "cancel": "cancel_appointment",
        "cancel_appointment": "cancel_appointment",
    }
    return aliases.get(normalized, normalized)


def _parse_tool_datetime(value: str | datetime | None, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _run_vapi_tool(db: Session, tool_name: str | None, args: dict) -> dict:
    tool_name = _canonical_tool_name(tool_name)
    if tool_name == "lookup_patient_by_phone":
        result = lookup_patient_by_phone(db, phone=str(args.get("phone", "")))
        if result.get("found"):
            appointments = result.get("active_appointments") or []
            if appointments:
                result["assistant_message"] = (
                    f"Patient found: {result['patient']['first_name']} {result['patient']['last_name']}. "
                    f"There are {len(appointments)} active future appointment(s). Tell the caller the appointment details and ask whether to reschedule, cancel, or book a new appointment."
                )
            else:
                result["assistant_message"] = (
                    f"Patient found: {result['patient']['first_name']} {result['patient']['last_name']}. "
                    "No active future appointments were found. Continue booking."
                )
        else:
            result["assistant_message"] = "No patient was found for this phone number. Ask for the caller's full name and create the patient record."
        return result
    if tool_name == "identify_or_create_patient":
        try:
            result = identify_or_create_patient(
                db,
                full_name=str(args.get("full_name", "")),
                preferred_language=args.get("preferred_language") or "en",
                phone=args.get("phone"),
                email=args.get("email"),
            )
            patient = result.get("patient") or {}
            result["assistant_message"] = (
                f"Patient record is ready: patient_id={patient.get('id')}, "
                f"name={patient.get('first_name')} {patient.get('last_name')}. Continue by asking for doctor or specialty."
            )
            return result
        except ValueError as exc:
            return {
                "created": False,
                "patient": None,
                "message": str(exc),
                "assistant_message": "The patient record was not created. Ask for the missing full name and try again.",
            }
    if tool_name == "search_doctors":
        doctors = search_doctors(db, query=args.get("query"), department=args.get("department"))
        if doctors:
            options = [
                f"doctor_id={doctor['id']}: Dr. {doctor['first_name']} {doctor['last_name']} ({doctor['specialty']}, {doctor.get('clinic_location') or 'location not listed'})"
                for doctor in doctors[:3]
            ]
            assistant_message = (
                f"Found {len(doctors)} matching doctor(s): " + "; ".join(options) + ". "
                "Use only these returned doctors. If there is one match, select it and ask for preferred date and time."
            )
        else:
            assistant_message = "No matching doctors were found in the database. Ask the caller for another specialty or doctor name."
        return {
            "doctors": doctors,
            "matched_count": len(doctors),
            "assistant_message": assistant_message,
            "assistant_directive": (
                "Use only the doctors returned in doctors. Do not invent doctor names, gender, branches, or extra options. "
                "If matched_count is 0, say no matching doctor was found and ask for another specialty. "
                "If matched_count is 1, select that doctor. If more than 1, read at most 3 returned options."
            ),
        }
    if tool_name == "check_appointment_availability":
        start = _parse_tool_datetime(args.get("scheduled_start"), field_name="scheduled_start")
        end = _parse_tool_datetime(args.get("scheduled_end"), field_name="scheduled_end")
        return check_appointment_availability(db, doctor_id=int(args["doctor_id"]), scheduled_start=start, scheduled_end=end)
    if tool_name == "book_appointment":
        start = _parse_tool_datetime(args.get("scheduled_start"), field_name="scheduled_start")
        end = _parse_tool_datetime(args.get("scheduled_end"), field_name="scheduled_end")
        return book_appointment(
            db,
            patient_id=int(args["patient_id"]),
            doctor_id=int(args["doctor_id"]),
            scheduled_start=start,
            scheduled_end=end,
            visit_type=args.get("visit_type") or "in_person",
            reason=args.get("reason") or "Booked by Vapi assistant",
            confirmation=bool(args.get("confirmation", True)),
        )
    if tool_name == "reschedule_appointment":
        start = _parse_tool_datetime(args.get("scheduled_start"), field_name="scheduled_start")
        end = _parse_tool_datetime(args.get("scheduled_end"), field_name="scheduled_end")
        return reschedule_appointment(
            db,
            appointment_code=str(args.get("appointment_code", "")),
            scheduled_start=start,
            scheduled_end=end,
            confirmation=bool(args.get("confirmation", True)),
        )
    if tool_name == "cancel_appointment":
        return cancel_appointment(
            db,
            appointment_code=str(args.get("appointment_code", "")),
            confirmation=bool(args.get("confirmation", True)),
        )
    raise ValueError(f"Unsupported Vapi tool: {tool_name}")


def _vapi_result(tool_call_id: str | None, result: dict | None = None, error: str | None = None) -> dict:
    item = {"toolCallId": tool_call_id or "unknown"}
    if error:
        item["error"] = error.replace("\n", " ")
    else:
        item["result"] = json.dumps(result or {}, default=str, ensure_ascii=False).replace("\n", " ")
    return item


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


@router.post("/patients/lookup-by-phone", response_model=PatientPhoneLookupResponse)
def lookup_patient_by_phone_route(
    payload: PatientPhoneLookupRequest,
    db: Session = Depends(get_db),
) -> PatientPhoneLookupResponse:
    result = lookup_patient_by_phone(db, phone=payload.phone)
    return PatientPhoneLookupResponse(**result)


@router.post("/doctors/search", response_model=list[DoctorResponse])
def search_doctors_route(payload: DoctorSearchRequest, db: Session = Depends(get_db)) -> list[DoctorResponse]:
    results = search_doctors(db, query=payload.query, department=payload.department)
    return [DoctorResponse(**item) for item in results]


@router.get("/debug/database-summary")
def database_summary_route(db: Session = Depends(get_db)) -> dict:
    return database_summary(db)


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


@router.post("/vapi/tools")
def vapi_single_tool_route(payload: dict, db: Session = Depends(get_db)) -> dict:
    tool_call_id, tool_name, args = _normalize_tool_call(payload)
    try:
        result = _run_vapi_tool(db, tool_name, args)
        return {"results": [_vapi_result(tool_call_id, result=result)]}
    except Exception as exc:
        return {"results": [_vapi_result(tool_call_id, error=str(exc))]}


@router.post("/vapi/tool-calls")
def vapi_tool_calls_route(payload: dict, db: Session = Depends(get_db)) -> dict:
    tool_calls = _extract_vapi_tool_calls(payload)
    if not tool_calls:
        return {"results": [_vapi_result(None, error="No Vapi tool calls found in payload")]}

    results = []
    for tool_call in tool_calls:
        tool_call_id, tool_name, args = _normalize_tool_call(tool_call)
        try:
            result = _run_vapi_tool(db, tool_name, args)
            results.append(_vapi_result(tool_call_id, result=result))
        except Exception as exc:
            results.append(_vapi_result(tool_call_id, error=str(exc)))
    return {"results": results}


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

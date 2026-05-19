"""LangGraph workflow for appointment booking and rescheduling."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.services import (
    book_appointment,
    check_appointment_availability,
    reschedule_appointment,
    verify_patient,
)


IntentType = Literal["book", "reschedule", "unknown"]


class AppointmentWorkflowState(TypedDict, total=False):
    user_input: str
    extracted_entities: dict[str, Any]
    language: str
    intent: IntentType
    patient_code: str
    phone: str
    date_of_birth: str
    patient_verified: bool
    patient: dict[str, Any] | None
    doctor_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    visit_type: str
    reason: str
    appointment_code: str
    availability: dict[str, Any]
    confirmation_summary: str
    user_confirmed: bool
    operation_result: dict[str, Any] | None
    error: str | None
    db_session: Session


def detect_language(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    text = (state.get("user_input") or "").strip()
    if any(ch in text for ch in ["ا", "ب", "ت", "ث", "ج", "ح"]):
        language = "ar"
    else:
        language = "en"
    return {"language": language}


def detect_intent(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    text = (state.get("user_input") or "").lower()
    if any(word in text for word in ["reschedule", "move", "change", "postpone"]):
        intent: IntentType = "reschedule"
    elif any(word in text for word in ["book", "schedule", "new appointment"]):
        intent = "book"
    else:
        intent = "unknown"
    return {"intent": intent}


def collect_patient_info(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    entities = state.get("extracted_entities") or {}
    updates: AppointmentWorkflowState = {}

    if "patient_code" in entities and not state.get("patient_code"):
        updates["patient_code"] = str(entities["patient_code"])
    if "phone" in entities and not state.get("phone"):
        updates["phone"] = str(entities["phone"])
    if "date_of_birth" in entities and not state.get("date_of_birth"):
        updates["date_of_birth"] = str(entities["date_of_birth"])

    return updates


def verify_patient_node(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    db = state.get("db_session")
    if db is None:
        return {"patient_verified": False, "patient": None, "error": "Missing db_session in workflow state."}

    result = verify_patient(
        db,
        patient_code=state.get("patient_code"),
        phone=state.get("phone"),
        date_of_birth=state.get("date_of_birth"),
    )
    return {"patient_verified": result["verified"], "patient": result["patient"]}


def collect_appointment_details(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    entities = state.get("extracted_entities") or {}
    updates: AppointmentWorkflowState = {}

    if "doctor_id" in entities and not state.get("doctor_id"):
        updates["doctor_id"] = int(entities["doctor_id"])
    if "scheduled_start" in entities and not state.get("scheduled_start"):
        updates["scheduled_start"] = entities["scheduled_start"]
    if "scheduled_end" in entities and not state.get("scheduled_end"):
        updates["scheduled_end"] = entities["scheduled_end"]
    if "visit_type" in entities and not state.get("visit_type"):
        updates["visit_type"] = str(entities["visit_type"])
    if "reason" in entities and not state.get("reason"):
        updates["reason"] = str(entities["reason"])
    if "appointment_code" in entities and not state.get("appointment_code"):
        updates["appointment_code"] = str(entities["appointment_code"])

    return updates


def check_availability(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    db = state.get("db_session")
    if db is None:
        return {"availability": {"available": False, "conflicting_appointment_codes": []}, "error": "Missing db_session in workflow state."}

    doctor_id = state.get("doctor_id")
    start = state.get("scheduled_start")
    end = state.get("scheduled_end")
    if doctor_id is None or start is None or end is None:
        return {
            "availability": {"available": False, "conflicting_appointment_codes": []},
            "error": "Missing doctor/time details for availability check.",
        }

    availability = check_appointment_availability(db, doctor_id=doctor_id, scheduled_start=start, scheduled_end=end)
    return {"availability": availability}


def generate_confirmation_summary(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    patient = state.get("patient") or {}
    availability = state.get("availability") or {}

    summary = (
        f"Intent: {state.get('intent', 'unknown')} | "
        f"Patient: {patient.get('first_name', 'N/A')} {patient.get('last_name', '')} | "
        f"Doctor ID: {state.get('doctor_id', 'N/A')} | "
        f"Start: {state.get('scheduled_start', 'N/A')} | "
        f"End: {state.get('scheduled_end', 'N/A')} | "
        f"Available: {availability.get('available', False)}"
    )
    return {"confirmation_summary": summary}


def wait_for_confirmation(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    # This node expects user_confirmed to be set by caller/UI layer.
    return {"user_confirmed": bool(state.get("user_confirmed", False))}


def save_or_reschedule(state: AppointmentWorkflowState) -> AppointmentWorkflowState:
    """Persist appointment changes only when explicitly confirmed.

    This node is the write barrier: if user_confirmed is false, no DB write service is called.
    """
    if not state.get("user_confirmed", False):
        return {
            "operation_result": {
                "success": False,
                "message": "Write blocked: user_confirmed is false.",
            }
        }

    db = state.get("db_session")
    if db is None:
        return {
            "operation_result": {
                "success": False,
                "message": "Write blocked: missing db_session.",
            }
        }

    intent = state.get("intent", "unknown")
    if intent == "book":
        result = book_appointment(
            db,
            patient_id=(state.get("patient") or {}).get("id"),
            doctor_id=state.get("doctor_id"),
            scheduled_start=state.get("scheduled_start"),
            scheduled_end=state.get("scheduled_end"),
            visit_type=state.get("visit_type", "in_person"),
            reason=state.get("reason"),
            confirmation=True,
        )
        return {"operation_result": result}

    if intent == "reschedule":
        result = reschedule_appointment(
            db,
            appointment_code=state.get("appointment_code", ""),
            scheduled_start=state.get("scheduled_start"),
            scheduled_end=state.get("scheduled_end"),
            confirmation=True,
        )
        return {"operation_result": result}

    return {
        "operation_result": {
            "success": False,
            "message": "No write performed: unsupported intent.",
        }
    }


def _should_continue_after_verify(state: AppointmentWorkflowState) -> Literal["continue", "stop"]:
    return "continue" if state.get("patient_verified", False) else "stop"


def _should_save(state: AppointmentWorkflowState) -> Literal["save", "stop"]:
    return "save" if state.get("user_confirmed", False) else "stop"


def build_appointment_workflow() -> Any:
    graph = StateGraph(AppointmentWorkflowState)

    graph.add_node("detect_language", detect_language)
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("collect_patient_info", collect_patient_info)
    graph.add_node("verify_patient", verify_patient_node)
    graph.add_node("collect_appointment_details", collect_appointment_details)
    graph.add_node("check_availability", check_availability)
    graph.add_node("generate_confirmation_summary", generate_confirmation_summary)
    graph.add_node("wait_for_confirmation", wait_for_confirmation)
    graph.add_node("save_or_reschedule", save_or_reschedule)

    graph.add_edge(START, "detect_language")
    graph.add_edge("detect_language", "detect_intent")
    graph.add_edge("detect_intent", "collect_patient_info")
    graph.add_edge("collect_patient_info", "verify_patient")

    graph.add_conditional_edges(
        "verify_patient",
        _should_continue_after_verify,
        {
            "continue": "collect_appointment_details",
            "stop": END,
        },
    )

    graph.add_edge("collect_appointment_details", "check_availability")
    graph.add_edge("check_availability", "generate_confirmation_summary")
    graph.add_edge("generate_confirmation_summary", "wait_for_confirmation")

    graph.add_conditional_edges(
        "wait_for_confirmation",
        _should_save,
        {
            "save": "save_or_reschedule",
            "stop": END,
        },
    )

    graph.add_edge("save_or_reschedule", END)

    return graph.compile()


appointment_workflow = build_appointment_workflow()

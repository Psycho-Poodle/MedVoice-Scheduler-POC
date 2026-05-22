"""OpenAI Realtime session integration service."""

from __future__ import annotations

import os
from typing import Any

import httpx

REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
DEFAULT_REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE", "alloy")


class OpenAISpeechError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _build_realtime_instructions() -> str:
    return (
        "You are MedVoice scheduling assistant for clinics. "
        "Support Arabic and English naturally. "
        "Accept user voice/text input and provide both text and audio responses. "
        "Your scope is patient verification, doctor/department search, availability checks, booking, and rescheduling. "
        "Before any booking/rescheduling write action, summarize details and ask for explicit confirmation. "
        "Never store or modify appointments unless user_confirmed is true in workflow input. "
        "For appointment operations, call tool run_appointment_workflow first. "
        "If workflow returns operation_result.success=false because confirmation is missing, ask user to confirm and retry with user_confirmed=true only after explicit consent."
    )


def _build_tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "run_appointment_workflow",
            "description": "Execute LangGraph appointment workflow for booking/rescheduling logic with confirmation guard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_input": {"type": "string"},
                    "extracted_entities": {
                        "type": "object",
                        "properties": {
                            "patient_code": {"type": "string"},
                            "phone": {"type": "string"},
                            "date_of_birth": {"type": "string"},
                            "doctor_id": {"type": "integer"},
                            "scheduled_start": {"type": "string", "format": "date-time"},
                            "scheduled_end": {"type": "string", "format": "date-time"},
                            "visit_type": {"type": "string"},
                            "reason": {"type": "string"},
                            "appointment_code": {"type": "string"}
                        },
                        "additionalProperties": True
                    },
                    "user_confirmed": {"type": "boolean"}
                },
                "required": ["user_input", "extracted_entities", "user_confirmed"],
                "additionalProperties": False
            }
        }
    ]


async def create_realtime_session(*, user_id: str | None = None) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    instructions = _build_realtime_instructions()
    if user_id:
        instructions += f" Current user id: {user_id}."

    payload: dict[str, Any] = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": {
            "type": "realtime",
            "model": DEFAULT_REALTIME_MODEL,
            "instructions": instructions,
            "tools": _build_tools_schema(),
            "tool_choice": "auto",
            "audio": {
                "output": {
                    "voice": DEFAULT_REALTIME_VOICE,
                }
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(REALTIME_CLIENT_SECRETS_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI realtime error {response.status_code}: {response.text}")
        return response.json()


async def synthesize_assistant_speech(*, text: str, voice: str | None = None) -> bytes:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    payload: dict[str, Any] = {
        "model": DEFAULT_REALTIME_MODEL,
        "voice": voice or DEFAULT_REALTIME_VOICE,
        "input": text,
        "response_format": "mp3",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(OPENAI_SPEECH_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise OpenAISpeechError(response.status_code, f"OpenAI speech error {response.status_code}: {response.text}")
        return response.content

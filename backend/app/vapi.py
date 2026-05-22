"""Vapi outbound calling client."""

from __future__ import annotations

import os
from typing import Any

import httpx

VAPI_BASE_URL = os.getenv("VAPI_BASE_URL", "https://api.vapi.ai")


class VapiConfigError(RuntimeError):
    pass


class VapiAPIError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise VapiConfigError(f"{name} is not set")
    return value


async def create_outbound_call(
    *,
    phone_number: str,
    appointment_code: str,
    patient_name: str,
    doctor_name: str,
    scheduled_start: str,
) -> dict[str, Any]:
    api_key = _required_env("VAPI_API_KEY")
    assistant_id = _required_env("VAPI_ASSISTANT_ID")
    phone_number_id = _required_env("VAPI_PHONE_NUMBER_ID")

    payload: dict[str, Any] = {
        "assistantId": assistant_id,
        "phoneNumberId": phone_number_id,
        "customer": {
            "number": phone_number,
            "name": patient_name,
        },
        "assistantOverrides": {
            "variableValues": {
                "appointmentCode": appointment_code,
                "patientName": patient_name,
                "doctorName": doctor_name,
                "appointmentTime": scheduled_start,
            }
        },
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{VAPI_BASE_URL}/call", headers=headers, json=payload)
        if response.status_code >= 400:
            raise VapiAPIError(f"Vapi call error {response.status_code}: {response.text}")
        return response.json()

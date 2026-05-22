"""Background Vapi appointment reminder scheduler."""

from __future__ import annotations

import asyncio
import os

from app.db import SessionLocal
from app.services import list_vapi_due_reminders, mark_vapi_call_started
from app.vapi import create_outbound_call


async def run_due_vapi_reminders(*, limit: int = 20) -> dict:
    result = {"attempted": 0, "started": 0, "errors": [], "calls": []}
    with SessionLocal() as db:
        due = list_vapi_due_reminders(db, limit=limit)
        result["attempted"] = len(due)
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
            except Exception as exc:
                result["errors"].append(f"{appt['appointment_code']}: {exc}")
    return result


async def vapi_reminder_loop() -> None:
    interval_seconds = int(os.getenv("VAPI_REMINDER_INTERVAL_SECONDS", "7200"))
    startup_delay = int(os.getenv("VAPI_REMINDER_STARTUP_DELAY_SECONDS", "30"))
    await asyncio.sleep(startup_delay)
    while True:
        if os.getenv("VAPI_REMINDER_ENABLED", "false").lower() in {"1", "true", "yes"}:
            await run_due_vapi_reminders()
        await asyncio.sleep(interval_seconds)

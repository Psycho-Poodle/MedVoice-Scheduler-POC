"""Pydantic schemas for API contracts."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AppointmentStatus(str, Enum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    confirmed_coming = "confirmed_coming"
    rescheduled = "rescheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class VisitType(str, Enum):
    in_person = "in_person"
    telemedicine = "telemedicine"
    follow_up = "follow_up"


class PatientVerificationRequest(BaseModel):
    patient_code: str | None = None
    phone: str | None = None
    date_of_birth: str | None = None


class PatientResponse(BaseModel):
    id: int
    patient_code: str
    first_name: str
    last_name: str
    date_of_birth: str | None = None
    phone: str | None = None
    email: str | None = None


class PatientVerificationResponse(BaseModel):
    verified: bool
    patient: PatientResponse | None = None


class PatientIdentifyRequest(BaseModel):
    full_name: str
    preferred_language: str | None = "en"
    phone: str | None = None
    email: str | None = None


class PatientIdentifyResponse(BaseModel):
    created: bool
    patient: PatientResponse


class PatientPhoneLookupRequest(BaseModel):
    phone: str


class PatientPhoneLookupResponse(BaseModel):
    found: bool
    patient: dict[str, Any] | None = None
    active_appointments: list[dict[str, Any]] = Field(default_factory=list)
    message: str


class DoctorSearchRequest(BaseModel):
    query: str | None = None
    department: str | None = None


class DoctorResponse(BaseModel):
    id: int
    doctor_code: str
    first_name: str
    last_name: str
    specialty: str
    clinic_location: str | None = None


class AvailabilityCheckRequest(BaseModel):
    doctor_id: int
    scheduled_start: datetime
    scheduled_end: datetime


class AvailabilityCheckResponse(BaseModel):
    available: bool
    conflicting_appointment_codes: list[str] = Field(default_factory=list)


class BookAppointmentRequest(BaseModel):
    patient_id: int
    doctor_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    visit_type: VisitType = VisitType.in_person
    reason: str | None = None
    confirmation: bool = False


class RescheduleAppointmentRequest(BaseModel):
    appointment_code: str
    scheduled_start: datetime
    scheduled_end: datetime
    confirmation: bool = False


class AppointmentResponse(BaseModel):
    appointment_code: str
    patient_id: int
    doctor_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    status: AppointmentStatus
    visit_type: VisitType
    reason: str | None = None


class ActionResponse(BaseModel):
    success: bool
    message: str


class BookAppointmentResponse(BaseModel):
    success: bool
    appointment: AppointmentResponse | None = None
    message: str


class RescheduleAppointmentResponse(BaseModel):
    success: bool
    appointment: AppointmentResponse | None = None
    message: str


class CancelAppointmentRequest(BaseModel):
    appointment_code: str
    confirmation: bool = False


class CancelAppointmentResponse(BaseModel):
    success: bool
    appointment: AppointmentResponse | None = None
    message: str


class RealtimeSessionRequest(BaseModel):
    user_id: str | None = None


class RealtimeSessionResponse(BaseModel):
    id: str | None = None
    client_secret: dict[str, Any] | None = None
    expires_at: int | None = None
    model: str | None = None
    modalities: list[str] | None = None
    voice: str | None = None
    raw: dict[str, Any]


class AssistantSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None


class VoiceTranscriptionRequest(BaseModel):
    audio_base64: str = Field(min_length=1)
    mime_type: str = "audio/pcm;rate=16000"


class VoiceTranscriptionResponse(BaseModel):
    transcript: str


class RunAppointmentWorkflowRequest(BaseModel):
    user_input: str
    extracted_entities: dict[str, Any] = Field(default_factory=dict)
    user_confirmed: bool = False


class RunAppointmentWorkflowResponse(BaseModel):
    state: dict[str, Any]

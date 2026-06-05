# Vapi Medical Center Call Assistant

This flow is for patient-initiated web calls from the frontend call button. It is not an automatic reminder/follow-up caller.

## Required URLs

Use a public backend URL in Vapi. For local testing, expose the backend with a tunnel and replace the base URL below.

- Tool webhook URL: `https://YOUR_BACKEND_HOST/api/v1/vapi/tool-calls`
- Local backend path: `http://localhost:8000/api/v1/vapi/tool-calls`
- Frontend env:
  - `VITE_VAPI_PUBLIC_KEY=your_vapi_public_key`
  - `VITE_VAPI_ASSISTANT_ID=your_assistant_id`

After changing frontend env values, restart the frontend container or dev server.

## Assistant Prompt

Use this as the assistant system prompt:

```text
You are MediAssist, a polite female medical center appointment assistant for a clinic in Saudi Arabia.

Your job is to help patients book, reschedule, or cancel appointments. You must support English and Arabic. Detect the patient's language from their speech. If the patient speaks Arabic, reply in Arabic. If the patient speaks English, reply in English. Keep your tone warm, calm, concise, and professional.

Start by greeting the patient and asking how you can help. Collect the same information required by the web chat flow:
- full name
- phone number
- desired action: book, reschedule, or cancel
- doctor name or specialty/department
- preferred date and time
- visit type if needed; default to in_person
- reason for visit if booking

Important phone lookup rule:
When the patient provides a phone number, always call lookup_patient_by_phone before booking.
If an active future appointment exists, tell the patient the appointment code, doctor, date, and time. Then ask:
"Would you like to reschedule this appointment, or would you like to book a new appointment?"
In Arabic, ask the same meaning naturally.

Booking rules:
- If the phone number does not exist, collect the full name and call identify_or_create_patient.
- Search doctors before booking if the patient gives a specialty, department, or doctor name.
- Check availability before booking or rescheduling.
- Confirm the exact doctor, date, time, and visit type before calling book_appointment or reschedule_appointment.
- Never book, reschedule, or cancel without explicit patient confirmation.
- Appointment duration is 30 minutes unless the patient or clinic says otherwise.
- Use ISO 8601 datetime with timezone when calling tools.

Safety and scope:
- Do not provide diagnosis, medical advice, prescriptions, or emergency triage.
- For urgent symptoms, advise the patient to contact emergency services or visit the nearest emergency department.
- If a requested slot is unavailable, apologize briefly and ask for another time.
- If the patient asks for something outside appointments, politely explain that you can help with booking, rescheduling, or cancellation.

Closing:
After a successful booking or reschedule, read back the appointment code, doctor name, date, and time.
After cancellation, confirm the appointment was cancelled.
```

## Voice Setup

In Vapi Dashboard:

1. Create an Assistant.
2. Set the first message to a bilingual greeting, for example:
   `Hello, this is MediAssist from the medical center. مرحباً، معك مساعد المركز الطبي. How may I help you today?`
3. Select a polite female voice that supports both English and Arabic. Prefer a multilingual female voice and test Arabic pronunciation before going live.
4. Use a model with tool/function calling enabled.
5. Add the tools below and set each tool server URL to:
   `https://YOUR_BACKEND_HOST/api/v1/vapi/tool-calls`
6. Keep each tool synchronous. Do not enable async mode for these booking tools.
7. Use the exact snake_case tool names below. Display labels can be friendly, but the tool/function name should remain snake_case.

The backend returns Vapi's required format:

```json
{
  "results": [
    {
      "toolCallId": "call_123",
      "result": "single-line JSON string"
    }
  ]
}
```

## Tools

Create these custom tools in Vapi. The names must match exactly.

### lookup_patient_by_phone

Description: Look up a patient by phone number and return active future appointments.

Parameters:

```json
{
  "type": "object",
  "properties": {
    "phone": { "type": "string", "description": "Patient phone number, preferably with country code." }
  },
  "required": ["phone"]
}
```

### identify_or_create_patient

Description: Find or create a patient record after collecting name and phone.

```json
{
  "type": "object",
  "properties": {
    "full_name": { "type": "string" },
    "preferred_language": { "type": "string", "enum": ["en", "ar"] },
    "phone": { "type": "string" },
    "email": { "type": "string" }
  },
  "required": ["full_name", "phone"]
}
```

### search_doctors

Description: Search doctors by name, specialty, department, or clinic location.

```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string" },
    "department": { "type": "string" }
  }
}
```

### check_appointment_availability

Description: Check whether a doctor is available for a requested time window.

```json
{
  "type": "object",
  "properties": {
    "doctor_id": { "type": "integer" },
    "scheduled_start": { "type": "string", "description": "ISO 8601 datetime." },
    "scheduled_end": { "type": "string", "description": "ISO 8601 datetime." }
  },
  "required": ["doctor_id", "scheduled_start", "scheduled_end"]
}
```

### book_appointment

Description: Book a confirmed appointment in Postgres.

```json
{
  "type": "object",
  "properties": {
    "patient_id": { "type": "integer" },
    "doctor_id": { "type": "integer" },
    "scheduled_start": { "type": "string" },
    "scheduled_end": { "type": "string" },
    "visit_type": { "type": "string", "enum": ["in_person", "telemedicine", "follow_up"] },
    "reason": { "type": "string" },
    "confirmation": { "type": "boolean" }
  },
  "required": ["patient_id", "doctor_id", "scheduled_start", "scheduled_end", "confirmation"]
}
```

### reschedule_appointment

Description: Reschedule an existing appointment after patient confirmation.

```json
{
  "type": "object",
  "properties": {
    "appointment_code": { "type": "string" },
    "scheduled_start": { "type": "string" },
    "scheduled_end": { "type": "string" },
    "confirmation": { "type": "boolean" }
  },
  "required": ["appointment_code", "scheduled_start", "scheduled_end", "confirmation"]
}
```

### cancel_appointment

Description: Cancel an appointment after patient confirmation.

```json
{
  "type": "object",
  "properties": {
    "appointment_code": { "type": "string" },
    "confirmation": { "type": "boolean" }
  },
  "required": ["appointment_code", "confirmation"]
}
```

## Quick Local Tests

Check phone lookup:

```http
POST http://localhost:8000/api/v1/patients/lookup-by-phone
Content-Type: application/json

{
  "phone": "+966566200435"
}
```

Simulate a Vapi tool call:

```http
POST http://localhost:8000/api/v1/vapi/tool-calls
Content-Type: application/json

{
  "message": {
    "toolCallList": [
      {
        "id": "test-1",
        "name": "lookup_patient_by_phone",
        "parameters": {
          "phone": "+966566200435"
        }
      }
    ]
  }
}
```

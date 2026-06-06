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
[Identity]
You are MediAssist, a polite female bilingual (Arabic/English) appointment assistant for a medical center in Saudi Arabia. Your only role is to help patients: (1) book, (2) reschedule, or (3) cancel appointments.

[Style (Voice-Optimized)]
- Warm, calm, concise, professional.
- Ask ONE question at a time. Do not read long lists.
- Keep responses short, usually 1-2 sentences.
- Confirm key details by repeating them back before any final action.
- If the caller provides multiple details at once, acknowledge briefly and ask only the next missing item.
- Do not ask optional preferences unless required to complete the tool call.
- Do not ask for doctor gender, branch, insurance, date of birth, email, or extra medical details unless the user volunteers it or a tool requires it.
- Move toward completion. Once you have the minimum required details, check availability, confirm once, perform the action, summarize, and end politely.

[Language Handling]
- Detect the caller's language and respond in the same language.
- If unclear or mixed, ask which they prefer: Arabic or English.
- Map language to tool value: preferred_language = "ar" for Arabic, "en" for English.

[Scope & Safety]
- Do NOT provide diagnosis, medical advice, prescriptions, or triage.
- If symptoms sound urgent or life-threatening, advise contacting local emergency services or visiting the nearest emergency department.
- If asked for anything outside appointment management, politely state you can only help with booking, rescheduling, or canceling.

[Timezone + Datetime Rules]
- Assume Asia/Riyadh timezone.
- All tool datetimes must be ISO 8601 strings.
- Appointment duration is 30 minutes unless the clinic/user specifies otherwise.
- When building scheduled_end: scheduled_end = scheduled_start + 30 minutes unless told otherwise.

[Phone Number Rules]
- Ask for the phone number early and confirm it back.
- Prefer E.164 with country code. Saudi example: +9665XXXXXXXX.
- If the caller gives a Saudi mobile starting with 05, convert it to +9665XXXXXXXX.
- When you have a phone number, ALWAYS call lookup_patient_by_phone BEFORE booking anything.

[Core Tool Rules (Critical)]
1. After collecting phone, call lookup_patient_by_phone({ phone }).
2. If lookup indicates patient not found, collect full_name and optionally email, then call identify_or_create_patient({ full_name, phone, preferred_language, email? }).
3. If booking or rescheduling, you MUST check availability first using check_appointment_availability({ doctor_id, scheduled_start, scheduled_end }).
4. Never call book_appointment, reschedule_appointment, or cancel_appointment unless:
   - you have explicitly asked for confirmation, and
   - the caller clearly agrees.
   Then set confirmation=true in the tool call.
5. If caller does not confirm, do not call the final action tool.

[Doctor Search Rules - Critical]
- You may only offer doctors returned by search_doctors.
- Never invent doctor names, doctor gender, branch, availability, or specialty.
- If search_doctors returns one doctor, select that doctor and continue.
- If search_doctors returns multiple doctors, present up to 3 returned doctors maximum and ask which one.
- If search_doctors returns no doctors, say no matching doctor was found and ask for another doctor or specialty.
- If the caller says "general medicine", "general doctor", "family doctor", "GP", or "primary care", search for Family Medicine.
- If the caller says "dermatologist", "skin doctor", "skin specialist", "skin clinic", or "skin problem", search for Dermatology.
- If the caller says "cardiologist", "heart doctor", "heart specialist", "heart clinic", "blood pressure", or "hypertension", search for Cardiology.
- Do not ask whether the caller prefers a male or female doctor unless the search results contain gender data. The current tool does not provide gender.
- Use the returned doctor_id exactly. Do not guess doctor_id.

[How to Handle Existing Future Appointment]
If lookup_patient_by_phone returns an active future appointment:
- Tell the caller the appointment_code, doctor, date, and time.
- Ask in the caller's language: "Would you like to reschedule this appointment, cancel it, or book a new appointment?"
- Continue based on their choice.

[Booking Flow]
1. Confirm the caller wants to book.
2. Ask for phone, then call lookup_patient_by_phone.
3. If patient not found: ask for full name, then call identify_or_create_patient with preferred_language.
4. Ask which doctor, specialty, or department, then call search_doctors.
5. Select a single returned doctor or ask the caller to choose from returned doctors only.
6. Ask for preferred date and time.
7. Default visit_type="in_person" unless the caller asks for telemedicine or follow_up.
8. Ask reason for visit briefly. If unclear, use "Consultation".
9. Build scheduled_start and scheduled_end, 30 minutes later.
10. Call check_appointment_availability.
11. If available: restate doctor, date/time, and visit type, then ask: "Should I book it?"
12. If yes: call book_appointment with patient_id, doctor_id, scheduled_start, scheduled_end, visit_type, reason, confirmation=true.
13. After success: read back appointment code, doctor name, date, time, and visit type. Then say goodbye and stop asking more questions.

[Reschedule Flow]
1. Ask for phone, then call lookup_patient_by_phone.
2. Identify the appointment_code to reschedule. If more than one future appointment, ask which one.
3. Ask for new preferred date/time.
4. Build scheduled_start/end.
5. Call check_appointment_availability using the same doctor_id from the appointment unless the caller explicitly changes doctors.
6. Restate new date/time and ask explicit confirmation to reschedule.
7. If yes: call reschedule_appointment({ appointment_code, scheduled_start, scheduled_end, confirmation:true }).
8. Summarize the updated appointment details. Then say goodbye and stop asking more questions.

[Cancel Flow]
1. Ask for phone, then call lookup_patient_by_phone.
2. Identify the appointment_code to cancel. If more than one, ask which one.
3. Ask explicit confirmation to cancel now.
4. If yes: call cancel_appointment({ appointment_code, confirmation:true }).
5. Confirm cancellation. Then say goodbye and stop asking more questions.

[Error Handling]
- If user input is unclear, ask them to repeat briefly.
- If availability is not found, apologize and ask for another time.
- If tools return errors or missing fields, apologize, ask for the missing detail, and try again.
- If a tool returns an assistant_directive, follow it exactly.
```

## Voice Setup

In Vapi Dashboard:

1. Create an Assistant.
2. Set the first message to a short bilingual greeting, for example:
   `Hello, this is MediAssist from the medical center. مرحبا، معك مساعد المركز الطبي. How may I help you today?`
3. Select a polite female voice that supports both English and Arabic. Prefer a multilingual female voice and test Arabic pronunciation before going live.
4. Use a model with tool/function calling enabled.
5. Add the tools below and set each tool server URL to:
   `https://YOUR_BACKEND_HOST/api/v1/vapi/tool-calls`
6. Keep each tool synchronous. Do not enable async mode for these booking tools.
7. Use the exact snake_case tool names below. Display labels can be friendly, but the tool/function name should remain snake_case.
8. Set each tool `maxTokens` to at least `500`. Low token limits can make Vapi truncate or ignore returned doctor data.

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

Description: Search real doctors from the clinic database by name, specialty, department, or clinic location. The assistant must only offer doctors returned by this tool.

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

Check deployed DB data:

```http
GET https://YOUR_BACKEND_HOST/api/v1/debug/database-summary
```

Expected seeded doctors:

```text
Dr. Hassan Al-Salem - Family Medicine
Dr. Maha Al-Zahrani - Cardiology
Dr. Rakan Al-Mutairi - Dermatology
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
        "name": "search_doctors",
        "parameters": {
          "query": "general medicine"
        }
      }
    ]
  }
}
```

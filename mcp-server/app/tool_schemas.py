"""JSON schemas for MCP tool arguments and outputs."""

TOOL_SCHEMAS = {
    "verify_patient": {
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_code": {"type": "string"},
                "phone": {"type": "string"},
                "date_of_birth": {"type": "string", "format": "date"}
            },
            "anyOf": [{"required": ["patient_code"]}, {"required": ["phone"]}],
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "verified": {"type": "boolean"},
                "patient": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "patient_code": {"type": "string"},
                                "first_name": {"type": "string"},
                                "last_name": {"type": "string"},
                                "date_of_birth": {"type": ["string", "null"]},
                                "phone": {"type": ["string", "null"]},
                                "email": {"type": ["string", "null"]}
                            },
                            "required": ["id", "patient_code", "first_name", "last_name"]
                        }
                    ]
                }
            },
            "required": ["verified", "patient"]
        }
    },
    "get_patient_appointments": {
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "integer"},
                "patient_code": {"type": "string"}
            },
            "anyOf": [{"required": ["patient_id"]}, {"required": ["patient_code"]}],
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "appointments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "appointment_code": {"type": "string"},
                            "patient_id": {"type": "integer"},
                            "doctor_id": {"type": "integer"},
                            "scheduled_start": {"type": "string", "format": "date-time"},
                            "scheduled_end": {"type": "string", "format": "date-time"},
                            "status": {"type": "string"},
                            "visit_type": {"type": "string"},
                            "reason": {"type": ["string", "null"]}
                        },
                        "required": ["appointment_code", "patient_id", "doctor_id", "scheduled_start", "scheduled_end", "status", "visit_type"]
                    }
                }
            },
            "required": ["appointments"]
        }
    },
    "check_availability": {
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "integer"},
                "scheduled_start": {"type": "string", "format": "date-time"},
                "scheduled_end": {"type": "string", "format": "date-time"},
                "exclude_appointment_code": {"type": "string"}
            },
            "required": ["doctor_id", "scheduled_start", "scheduled_end"],
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "conflicting_appointment_codes": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"}
            },
            "required": ["available", "conflicting_appointment_codes", "message"]
        }
    },
    "book_appointment": {
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "integer"},
                "doctor_id": {"type": "integer"},
                "scheduled_start": {"type": "string", "format": "date-time"},
                "scheduled_end": {"type": "string", "format": "date-time"},
                "visit_type": {"type": "string"},
                "reason": {"type": "string"},
                "confirmation": {"type": "boolean"}
            },
            "required": ["patient_id", "doctor_id", "scheduled_start", "scheduled_end", "confirmation"],
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "appointment": {"type": ["object", "null"]}
            },
            "required": ["success", "message", "appointment"]
        }
    },
    "reschedule_appointment": {
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_code": {"type": "string"},
                "scheduled_start": {"type": "string", "format": "date-time"},
                "scheduled_end": {"type": "string", "format": "date-time"},
                "confirmation": {"type": "boolean"}
            },
            "required": ["appointment_code", "scheduled_start", "scheduled_end", "confirmation"],
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "appointment": {"type": ["object", "null"]}
            },
            "required": ["success", "message", "appointment"]
        }
    },
    "search_doctor_or_department": {
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "department": {"type": "string"}
            },
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "doctor_code": {"type": "string"},
                            "first_name": {"type": "string"},
                            "last_name": {"type": "string"},
                            "specialty": {"type": "string"},
                            "clinic_location": {"type": ["string", "null"]}
                        },
                        "required": ["id", "doctor_code", "first_name", "last_name", "specialty"]
                    }
                }
            },
            "required": ["results"]
        }
    },
    "get_clinic_policy": {
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"}
            },
            "additionalProperties": False
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "policy": {"type": "string"}
            },
            "required": ["topic", "policy"]
        }
    }
}

-- db/init.sql
-- Core schema bootstrap for MedVoice Scheduler

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS patients (
    id BIGSERIAL PRIMARY KEY,
    patient_code VARCHAR(32) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE,
    gender VARCHAR(20),
    phone VARCHAR(30),
    email VARCHAR(255),
    preferred_language VARCHAR(50) DEFAULT 'en',
    notes TEXT,
    profile_embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS doctors (
    id BIGSERIAL PRIMARY KEY,
    doctor_code VARCHAR(32) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    specialty VARCHAR(120) NOT NULL,
    phone VARCHAR(30),
    email VARCHAR(255),
    clinic_location VARCHAR(255),
    bio TEXT,
    profile_embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS appointments (
    id BIGSERIAL PRIMARY KEY,
    appointment_code VARCHAR(40) UNIQUE NOT NULL,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id BIGINT NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'scheduled',
    visit_type VARCHAR(30) NOT NULL DEFAULT 'in_person',
    reason TEXT,
    created_by VARCHAR(50) DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (scheduled_end > scheduled_start),
    CHECK (status IN ('scheduled', 'confirmed', 'confirmed_coming', 'rescheduled', 'completed', 'cancelled', 'no_show')),
    CHECK (visit_type IN ('in_person', 'telemedicine', 'follow_up'))
);

CREATE TABLE IF NOT EXISTS conversation_logs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL,
    appointment_id BIGINT REFERENCES appointments(id) ON DELETE SET NULL,
    patient_id BIGINT REFERENCES patients(id) ON DELETE SET NULL,
    doctor_id BIGINT REFERENCES doctors(id) ON DELETE SET NULL,
    role VARCHAR(20) NOT NULL,
    channel VARCHAR(30) NOT NULL DEFAULT 'voice',
    message_text TEXT NOT NULL,
    language VARCHAR(20) DEFAULT 'en',
    sentiment_score NUMERIC(5,2),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    message_embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (role IN ('patient', 'doctor', 'assistant', 'system')),
    CHECK (channel IN ('voice', 'chat', 'phone', 'email'))
);

CREATE INDEX IF NOT EXISTS idx_patients_patient_code ON patients(patient_code);
CREATE INDEX IF NOT EXISTS idx_doctors_doctor_code ON doctors(doctor_code);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_id ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_id ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_appointments_scheduled_start ON appointments(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_conversation_id ON conversation_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_appointment_id ON conversation_logs(appointment_id);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_created_at ON conversation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_metadata_gin ON conversation_logs USING gin(metadata);

-- pgvector indexes (for similarity search)
CREATE INDEX IF NOT EXISTS idx_patients_profile_embedding_ivfflat
    ON patients USING ivfflat (profile_embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_doctors_profile_embedding_ivfflat
    ON doctors USING ivfflat (profile_embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_conversation_logs_message_embedding_ivfflat
    ON conversation_logs USING ivfflat (message_embedding vector_cosine_ops)
    WITH (lists = 100);

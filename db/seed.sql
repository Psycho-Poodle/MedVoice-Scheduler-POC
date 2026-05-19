-- db/seed.sql
-- Demo seed data for MedVoice Scheduler

INSERT INTO patients (patient_code, first_name, last_name, date_of_birth, gender, phone, email, preferred_language, notes)
VALUES
('PAT-1001', 'Aisha', 'Al-Harbi', '1992-04-15', 'female', '+966500000101', 'aisha.harbi@example.com', 'ar', 'Prefers evening appointments.'),
('PAT-1002', 'Omar', 'Al-Qahtani', '1986-09-03', 'male', '+966500000102', 'omar.qahtani@example.com', 'ar', 'Follow-up for blood pressure management.'),
('PAT-1003', 'Lina', 'Al-Dossari', '2000-12-21', 'female', '+966500000103', 'lina.dossari@example.com', 'en', 'New patient intake.')
ON CONFLICT (patient_code) DO NOTHING;

INSERT INTO doctors (doctor_code, first_name, last_name, specialty, phone, email, clinic_location, bio)
VALUES
('DOC-2001', 'Hassan', 'Al-Salem', 'Family Medicine', '+966500001201', 'hassan.salem@medvoice.demo', 'Riyadh - North Clinic', 'Family physician focused on preventive care.'),
('DOC-2002', 'Maha', 'Al-Zahrani', 'Cardiology', '+966500001202', 'maha.zahrani@medvoice.demo', 'Riyadh - Heart Center', 'Cardiologist specializing in hypertension and arrhythmia.'),
('DOC-2003', 'Rakan', 'Al-Mutairi', 'Dermatology', '+966500001203', 'rakan.mutairi@medvoice.demo', 'Riyadh - West Clinic', 'Dermatologist with interest in chronic skin conditions.')
ON CONFLICT (doctor_code) DO NOTHING;

INSERT INTO appointments (
    appointment_code,
    patient_id,
    doctor_id,
    scheduled_start,
    scheduled_end,
    status,
    visit_type,
    reason,
    created_by
)
SELECT
    'APT-3001', p.id, d.id,
    NOW() + INTERVAL '1 day', NOW() + INTERVAL '1 day 30 minutes',
    'confirmed', 'in_person', 'Routine annual check-up', 'seed-script'
FROM patients p
JOIN doctors d ON d.doctor_code = 'DOC-2001'
WHERE p.patient_code = 'PAT-1001'
ON CONFLICT (appointment_code) DO NOTHING;

INSERT INTO appointments (
    appointment_code,
    patient_id,
    doctor_id,
    scheduled_start,
    scheduled_end,
    status,
    visit_type,
    reason,
    created_by
)
SELECT
    'APT-3002', p.id, d.id,
    NOW() + INTERVAL '2 days', NOW() + INTERVAL '2 days 45 minutes',
    'scheduled', 'follow_up', 'Blood pressure follow-up consultation', 'seed-script'
FROM patients p
JOIN doctors d ON d.doctor_code = 'DOC-2002'
WHERE p.patient_code = 'PAT-1002'
ON CONFLICT (appointment_code) DO NOTHING;

INSERT INTO appointments (
    appointment_code,
    patient_id,
    doctor_id,
    scheduled_start,
    scheduled_end,
    status,
    visit_type,
    reason,
    created_by
)
SELECT
    'APT-3003', p.id, d.id,
    NOW() + INTERVAL '3 days', NOW() + INTERVAL '3 days 20 minutes',
    'scheduled', 'telemedicine', 'Initial skin rash assessment', 'seed-script'
FROM patients p
JOIN doctors d ON d.doctor_code = 'DOC-2003'
WHERE p.patient_code = 'PAT-1003'
ON CONFLICT (appointment_code) DO NOTHING;

INSERT INTO conversation_logs (
    conversation_id,
    appointment_id,
    patient_id,
    doctor_id,
    role,
    channel,
    message_text,
    language,
    sentiment_score,
    metadata
)
SELECT
    '11111111-1111-1111-1111-111111111111'::uuid,
    a.id,
    p.id,
    d.id,
    'assistant',
    'voice',
    'Your appointment is confirmed for tomorrow at 10:00 AM.',
    'en',
    0.85,
    '{"event":"appointment_confirmation"}'::jsonb
FROM appointments a
JOIN patients p ON p.id = a.patient_id
JOIN doctors d ON d.id = a.doctor_id
WHERE a.appointment_code = 'APT-3001';

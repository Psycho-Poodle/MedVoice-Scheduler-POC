import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

type Lang = "en" | "ar";
type Role = "assistant" | "user" | "system";
type Stage = "ask_name" | "ask_intent" | "ask_doctor" | "ask_datetime" | "await_confirmation" | "completed";
type Intent = "book" | "reschedule" | "cancel" | "unknown";

type ChatMessage = {
  id: string;
  role: Role;
  text: string;
  time: string;
  voice?: boolean;
};

type Doctor = {
  id: number;
  first_name: string;
  last_name: string;
  specialty: string;
  clinic_location?: string;
};

type ActivePatient = {
  id: number;
  patient_code: string;
  first_name: string;
  last_name: string;
  email?: string | null;
};

type Draft = {
  intent: Intent;
  doctor: Doctor | null;
  start: Date | null;
  appointmentCode: string | null;
};

type ConversationSession = {
  id: string;
  title: string;
  createdAt: number;
  messages: ChatMessage[];
  stage: Stage;
  patient: ActivePatient | null;
  verified: boolean;
  draft: Draft;
  summary: string;
};

declare global {
  interface Window {
    webkitSpeechRecognition?: new () => SpeechRecognition;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const STORE_KEY = "medvoice_sessions_v1";

const now = () => new Date().toLocaleTimeString();
const formatDate = (d: Date) => d.toLocaleDateString(undefined, { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
const formatTime = (d: Date) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

const phrases = {
  en: {
    welcome: "Welcome. I can help you book, reschedule, or cancel an appointment. May I know your full name?",
    greet: (name: string) => `Thank you ${name}. How can I help you today: booking, rescheduling, or cancellation?`,
    askDoctor: "Please tell me the doctor name or department. You may also say: show doctor list.",
    askDateTime: "Please share your preferred date and time. Example: tomorrow 10:00 AM.",
    askConfirm: (doctor: string, dt: Date) => `I found an available slot on ${formatDate(dt)} at ${formatTime(dt)} with ${doctor}. Would you like me to confirm this appointment?`,
    booked: "Thank you. Your appointment has been successfully booked. Thank you for choosing our clinic.",
    thanksReply: "You're welcome. If you want to book, reschedule, or cancel an appointment, please tell me and I’ll help right away.",
    clarification: "I want to make sure I understood correctly. Would you like to book, reschedule, or cancel?",
    fallback: "I’m sorry, I didn’t fully understand. I can help with booking, rescheduling, or cancellation.",
    needDoctor: "Before confirmation, please tell me the doctor or department.",
    needDateTime: "Before confirmation, please share date and time.",
    noDoctors: "I could not load doctors right now. Please try again in a moment.",
    invalidDate: "I could not understand that date/time. Please try like: tomorrow 10:30 AM.",
    unavailable: "This slot is not available. I can help you choose another time.",
    askAppointmentCode: "Please share your appointment code so I can proceed.",
    cancelled: "Thank you. Your appointment has been successfully cancelled.",
    rescheduled: "Thank you. Your appointment has been successfully rescheduled.",
    goodbye: "Thank you for visiting. Wishing you good health.",
  },
  ar: {
    welcome: "مرحباً. يمكنني مساعدتك في حجز أو إعادة جدولة أو إلغاء موعد. ما اسمك الكامل؟",
    greet: (name: string) => `شكراً ${name}. كيف يمكنني مساعدتك اليوم: حجز أم إعادة جدولة أم إلغاء؟`,
    askDoctor: "من فضلك اذكر اسم الطبيب أو القسم. ويمكنك قول: اعرض قائمة الأطباء.",
    askDateTime: "من فضلك اذكر التاريخ والوقت المناسبين. مثال: غداً 10:00 صباحاً.",
    askConfirm: (doctor: string, dt: Date) => `وجدت موعداً متاحاً يوم ${formatDate(dt)} الساعة ${formatTime(dt)} مع ${doctor}. هل ترغب بتأكيد هذا الموعد؟`,
    booked: "شكراً لك. تم تأكيد موعدك بنجاح. شكراً لاختيارك عيادتنا.",
    thanksReply: "على الرحب والسعة. إذا رغبت بالحجز أو إعادة الجدولة أو الإلغاء، أخبرني وسأساعدك مباشرة.",
    clarification: "أريد التأكد من فهمي بشكل صحيح. هل ترغب في الحجز أم إعادة الجدولة أم الإلغاء؟",
    fallback: "عذراً، لم أفهم طلبك بالكامل. يمكنني المساعدة في الحجز أو إعادة الجدولة أو الإلغاء.",
    needDoctor: "قبل التأكيد، يرجى تحديد الطبيب أو القسم.",
    needDateTime: "قبل التأكيد، يرجى تحديد التاريخ والوقت.",
    noDoctors: "تعذر تحميل قائمة الأطباء حالياً. حاول مرة أخرى بعد قليل.",
    invalidDate: "لم أتمكن من فهم التاريخ/الوقت. جرّب مثلاً: غداً 10:30 صباحاً.",
    unavailable: "هذا الموعد غير متاح. أستطيع مساعدتك في اختيار وقت آخر.",
    askAppointmentCode: "يرجى تزويدي برمز الموعد للمتابعة.",
    cancelled: "شكراً لك. تم إلغاء الموعد بنجاح.",
    rescheduled: "شكراً لك. تم إعادة جدولة الموعد بنجاح.",
    goodbye: "شكراً لزيارتك. نتمنى لك دوام الصحة.",
  },
};

function extractName(input: string): string {
  const trimmed = input.trim();
  const patterns = [/my name is\s+(.+)/i, /i am\s+(.+)/i, /this is\s+(.+)/i, /اسمي\s+(.+)/i, /انا\s+(.+)/i];
  for (const p of patterns) {
    const m = trimmed.match(p);
    if (m?.[1]) return m[1].trim();
  }
  return trimmed;
}

function detectIntent(text: string): { intent: Intent; confidence: number } {
  const t = text.toLowerCase();
  const has = (arr: string[]) => arr.some((k) => t.includes(k));
  if (has(["book", "appointment", "حجز", "موعد"])) return { intent: "book", confidence: 0.86 };
  if (has(["reschedule", "change", "move", "إعادة", "تغيير"])) return { intent: "reschedule", confidence: 0.84 };
  if (has(["cancel", "إلغاء"])) return { intent: "cancel", confidence: 0.82 };
  return { intent: "unknown", confidence: 0.2 };
}

function isThanks(text: string) {
  const t = text.toLowerCase();
  return ["thanks", "thank you", "appreciate", "شكرا", "شكراً"].some((k) => t.includes(k));
}

function isConfirm(text: string) {
  const t = text.toLowerCase();
  return ["yes", "confirm", "go ahead", "book it", "تأكيد", "نعم", "موافق"].some((k) => t.includes(k));
}

function parseAppointmentCode(text: string): string | null {
  const match = text.match(/apt[-\s]?[a-z0-9]{4,}/i);
  return match ? match[0].toUpperCase().replace(" ", "-") : null;
}

function parseDateTime(text: string): Date | null {
  const lower = text.toLowerCase();
  const d = new Date();
  let base = new Date(d);
  if (lower.includes("tomorrow") || lower.includes("غد")) base.setDate(base.getDate() + 1);

  const monthMap: Record<string, number> = {
    jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3, may: 4, jun: 5, june: 5,
    jul: 6, july: 6, aug: 7, august: 7, sep: 8, sept: 8, september: 8, oct: 9, october: 9, nov: 10, november: 10, dec: 11, december: 11,
  };

  // Examples: 28th May, 30may, 30 May 2026
  const explicit = lower.match(/(\d{1,2})(?:st|nd|rd|th)?\s*([a-z]{3,9})(?:\s*(\d{4}))?/i);
  if (explicit) {
    const day = Number(explicit[1]);
    const month = monthMap[explicit[2].toLowerCase()];
    if (month !== undefined) {
      const year = explicit[3] ? Number(explicit[3]) : base.getFullYear();
      base = new Date(year, month, day, 0, 0, 0, 0);
    }
  }

  const dateMatch = lower.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (dateMatch) base = new Date(`${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}T00:00:00`);
  const timeMatch = lower.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
  if (!timeMatch) return null;
  let h = Number(timeMatch[1]);
  const m = Number(timeMatch[2] || 0);
  const meridian = (timeMatch[3] || "").toLowerCase();
  if (meridian === "pm" && h < 12) h += 12;
  if (meridian === "am" && h === 12) h = 0;
  base.setHours(h, m, 0, 0);
  return base;
}

function mkNewSession(lang: Lang): ConversationSession {
  return {
    id: crypto.randomUUID(),
    title: "New Conversation",
    createdAt: Date.now(),
    messages: [{ id: crypto.randomUUID(), role: "assistant", text: phrases[lang].welcome, time: now() }],
    stage: "ask_name",
    patient: null,
    verified: false,
    draft: { intent: "unknown", doctor: null, start: null, appointmentCode: null },
    summary: "",
  };
}

function App() {
  const [lang, setLang] = useState<Lang>("en");
  const dir = lang === "ar" ? "rtl" : "ltr";
  const p = phrases[lang];

  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [chatSearch, setChatSearch] = useState("");
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceMode, setVoiceMode] = useState("idle");
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ConversationSession[];
      if (parsed.length) {
        setSessions(parsed);
        setActiveId(parsed[0].id);
        return;
      }
    }
    const first = mkNewSession("en");
    setSessions([first]);
    setActiveId(first.id);
  }, []);

  useEffect(() => {
    if (sessions.length) localStorage.setItem(STORE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  const active = sessions.find((s) => s.id === activeId) || sessions[0];

  const updateActive = (mutator: (s: ConversationSession) => ConversationSession) => {
    setSessions((prev) => prev.map((s) => (s.id === activeId ? mutator(s) : s)));
  };

  const addMsg = (role: Role, text: string, voice = false) => {
    updateActive((s) => ({ ...s, messages: [...s.messages, { id: crypto.randomUUID(), role, text, time: now(), voice }] }));
  };

  const grouped = useMemo(() => {
    const list = sessions.filter((s) => s.title.toLowerCase().includes(chatSearch.toLowerCase()));
    return {
      today: list.slice(0, 4),
      yesterday: list.slice(4, 8),
      week: list.slice(8),
    };
  }, [sessions, chatSearch]);

  const fetchDoctors = async (): Promise<Doctor[]> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/doctors/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      const data = await res.json();
      const list = Array.isArray(data) ? data : [];
      setDoctors(list);
      return list;
    } catch {
      addMsg("assistant", p.noDoctors);
      return [];
    }
  };

  const identifyPatient = async (nameRaw: string) => {
    const name = extractName(nameRaw);
    const res = await fetch(`${API_BASE}/api/v1/patients/identify-or-create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: name, preferred_language: lang }),
    });
    const data = await res.json();
    updateActive((s) => ({ ...s, patient: data.patient, verified: true, title: `${data.patient.first_name} ${data.patient.last_name}` }));
    addMsg("assistant", p.greet(`${data.patient.first_name} ${data.patient.last_name}`));
    updateActive((s) => ({ ...s, stage: "ask_intent" }));
  };

  const runAppointmentAction = async (confirm: boolean, naturalText: string) => {
    if (!active?.patient || !active?.draft?.doctor || !active?.draft?.start) {
      addMsg("assistant", !active?.draft?.doctor ? p.needDoctor : p.needDateTime);
      return;
    }

    const end = new Date(active.draft.start.getTime() + 30 * 60 * 1000);
    const forcedIntentText = confirm
      ? `${active.draft.intent} appointment confirm`
      : `${active.draft.intent} appointment`;

    if (!confirm) {
      const d = active.draft.start;
      const doctor = `Dr. ${active.draft.doctor.first_name} ${active.draft.doctor.last_name}`;
      const humanSummary = p.askConfirm(doctor, d);
      updateActive((s) => ({ ...s, summary: humanSummary, stage: "await_confirmation" }));
      addMsg("assistant", humanSummary);
      return;
    }

    if (active.draft.intent === "book") {
      const res = await fetch(`${API_BASE}/api/v1/langgraph/appointment/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_input: forcedIntentText,
          extracted_entities: {
            patient_code: active.patient.patient_code,
            doctor_id: active.draft.doctor.id,
            scheduled_start: active.draft.start.toISOString(),
            scheduled_end: end.toISOString(),
            visit_type: "in_person",
            reason: naturalText || "Consultation",
          },
          user_confirmed: true,
        }),
      });
      const data = await res.json();
      const op = data?.state?.operation_result;
      if (op?.success) {
        const code = op?.appointment?.appointment_code || null;
        updateActive((s) => ({ ...s, stage: "completed", draft: { ...s.draft, appointmentCode: code } }));
        addMsg("assistant", p.booked);
      } else {
        addMsg("assistant", p.unavailable);
      }
      return;
    }

    if (active.draft.intent === "reschedule") {
      if (!active.draft.appointmentCode) {
        addMsg("assistant", p.askAppointmentCode);
        return;
      }
      const res = await fetch(`${API_BASE}/api/v1/appointments/reschedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          appointment_code: active.draft.appointmentCode,
          scheduled_start: active.draft.start.toISOString(),
          scheduled_end: end.toISOString(),
          confirmation: true,
        }),
      });
      if (res.ok) {
        updateActive((s) => ({ ...s, stage: "completed" }));
        addMsg("assistant", p.rescheduled);
      } else {
        addMsg("assistant", p.unavailable);
      }
      return;
    }

    if (active.draft.intent === "cancel") {
      if (!active.draft.appointmentCode) {
        addMsg("assistant", p.askAppointmentCode);
        return;
      }
      const res = await fetch(`${API_BASE}/api/v1/appointments/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          appointment_code: active.draft.appointmentCode,
          confirmation: true,
        }),
      });
      if (res.ok) {
        updateActive((s) => ({ ...s, stage: "completed", summary: p.cancelled }));
        addMsg("assistant", p.cancelled);
      } else {
        addMsg("assistant", p.unavailable);
      }
      return;
    }

    const res = await fetch(`${API_BASE}/api/v1/langgraph/appointment/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_input: forcedIntentText,
        extracted_entities: {
          patient_code: active.patient.patient_code,
          doctor_id: active.draft.doctor.id,
          scheduled_start: active.draft.start.toISOString(),
          scheduled_end: end.toISOString(),
          visit_type: "in_person",
          reason: naturalText || "Consultation",
        },
        user_confirmed: confirm,
      }),
    });

    const data = await res.json();
    const op = data?.state?.operation_result;
    if (op?.success) {
      addMsg("assistant", p.booked);
      updateActive((s) => ({ ...s, stage: "completed" }));
    } else {
      addMsg("assistant", p.unavailable);
    }
  };

  const handleText = async (text: string, voice = false) => {
    if (!text.trim()) return;
    addMsg("user", text, voice);

    if (!active) return;

    const codeInMessage = parseAppointmentCode(text);
    if (codeInMessage) {
      updateActive((s) => ({ ...s, draft: { ...s.draft, appointmentCode: codeInMessage } }));
      addMsg("assistant", `Appointment code ${codeInMessage} recorded.`);
    }

    const globalIntent = detectIntent(text);
    if (globalIntent.confidence >= 0.55 && globalIntent.intent !== "unknown") {
      updateActive((s) => ({
        ...s,
        draft: { ...s.draft, intent: globalIntent.intent },
        stage: globalIntent.intent === "cancel" ? "await_confirmation" : s.stage === "ask_intent" ? "ask_doctor" : s.stage,
      }));
      if (globalIntent.intent === "cancel") {
        addMsg("assistant", active?.draft?.appointmentCode || codeInMessage ? "Please confirm cancellation." : p.askAppointmentCode);
        return;
      }
      if (active?.stage === "ask_intent") {
        addMsg("assistant", p.askDoctor);
        return;
      }
    }

    if (isThanks(text)) {
      addMsg("assistant", p.thanksReply);
      // Continue to parse intent from same/next user messages naturally.
    }

    if (["bye", "goodbye", "exit", "مع السلامة", "خروج"].some((k) => text.toLowerCase().includes(k))) {
      addMsg("assistant", p.goodbye);
      return;
    }

    if (active.stage === "ask_name") {
      await identifyPatient(text);
      return;
    }

    if (active.stage === "ask_intent") {
      const intentRes = detectIntent(text);
      if (intentRes.confidence < 0.55 || intentRes.intent === "unknown") {
        addMsg("assistant", p.clarification);
        return;
      }
      updateActive((s) => ({ ...s, draft: { ...s.draft, intent: intentRes.intent }, stage: "ask_doctor" }));
      addMsg("assistant", p.askDoctor);
      return;
    }

    if (active.stage === "ask_doctor") {
      if (["doctor list", "available doctors", "قائمة", "الأطباء"].some((k) => text.toLowerCase().includes(k))) {
        const list = doctors.length ? doctors : await fetchDoctors();
        if (list.length) {
          addMsg("assistant", list.map((d) => `Dr. ${d.first_name} ${d.last_name} (${d.specialty})`).join("\n"));
          addMsg("assistant", p.askDoctor);
        }
        return;
      }

      const list = doctors.length ? doctors : await fetchDoctors();
      const lower = text.toLowerCase();
      const doctor = list.find((d) => {
        const full = `${d.first_name} ${d.last_name}`.toLowerCase();
        return lower.includes(full) || lower.includes(d.specialty.toLowerCase());
      });
      if (!doctor) {
        addMsg("assistant", p.needDoctor);
        return;
      }

      updateActive((s) => ({ ...s, draft: { ...s.draft, doctor }, stage: "ask_datetime" }));
      addMsg("assistant", p.askDateTime);
      return;
    }

    if (active.stage === "ask_datetime") {
      const dt = parseDateTime(text);
      if (!dt) {
        addMsg("assistant", p.invalidDate);
        return;
      }
      updateActive((s) => ({ ...s, draft: { ...s.draft, start: dt } }));
      await runAppointmentAction(false, text);
      return;
    }

    if (active.stage === "await_confirmation") {
      if (!isConfirm(text)) {
        addMsg("assistant", p.clarification);
        return;
      }
      await runAppointmentAction(true, text);
      return;
    }

    if (active.stage === "completed") {
      const i = detectIntent(text);
      if (i.intent === "unknown") {
        addMsg("assistant", p.thanksReply);
        return;
      }
      updateActive((s) => ({ ...s, draft: { ...s.draft, intent: i.intent }, stage: i.intent === "cancel" ? "await_confirmation" : "ask_doctor" }));
      addMsg("assistant", i.intent === "cancel" ? (active.draft.appointmentCode ? "Please confirm cancellation." : p.askAppointmentCode) : p.askDoctor);
      return;
    }

    addMsg("assistant", p.fallback);
  };

  const startVoice = async () => {
    setVoiceMode("connecting");
    try {
      const res = await fetch(`${API_BASE}/api/v1/realtime/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: active?.patient?.patient_code ?? "visitor" }),
      });
      if (!res.ok) throw new Error();
      setVoiceMode("ready");

      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) {
        addMsg("system", "Voice recognition is not supported in this browser. Please use Chrome or Edge.");
        return;
      }
      const rec = new SR();
      rec.lang = lang === "ar" ? "ar-SA" : "en-US";
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.onstart = () => setListening(true);
      rec.onend = () => setListening(false);
      rec.onerror = () => setListening(false);
      rec.onresult = async (e: SpeechRecognitionEvent) => {
        const r = e.results[e.results.length - 1];
        const txt = r[0].transcript.trim();
        if (r.isFinal && txt) await handleText(txt, true);
      };
      recognitionRef.current = rec;
      rec.start();
    } catch {
      setVoiceMode("error");
      addMsg("assistant", p.fallback);
    }
  };

  const onSend = async () => {
    const t = input.trim();
    if (!t) return;
    setInput("");
    await handleText(t);
  };

  const newConversation = () => {
    const s = mkNewSession(lang);
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
  };

  if (!active) return null;

  return (
    <div className={`page ${lang}`} dir={dir}>
      <aside className="left-sidebar panel">
        <div>
          <div className="brand"><div className="brand-dot" /><div><h1>MediAssist AI</h1><p>Multilingual AI Patient Booking & Rescheduling Assistant</p></div></div>
          <button className="primary-btn" onClick={newConversation}>+ New Conversation</button>
          <input className="search" placeholder="Search chats" value={chatSearch} onChange={(e) => setChatSearch(e.target.value)} />
          <ChatGroup title="Today" items={grouped.today} active={activeId} onPick={setActiveId} />
          <ChatGroup title="Yesterday" items={grouped.yesterday} active={activeId} onPick={setActiveId} />
          <ChatGroup title="Previous 7 Days" items={grouped.week} active={activeId} onPick={setActiveId} />
        </div>
        <div className="profile-box"><p className="small">Profile</p><strong>{active.patient ? `${active.patient.first_name} ${active.patient.last_name}` : "Guest"}</strong><p className="small">{active.patient?.email || "guest@medvoice.local"}</p><div className="profile-actions"><button>Settings</button><button>Logout</button></div></div>
      </aside>

      <main className="chat-main panel">
        <header className="chat-header"><div><h2>MediAssist AI</h2><span className="online">Online</span></div><div className="header-tools"><span>Language: {lang.toUpperCase()}</span><span>Voice mode: {voiceMode}</span><button className="lang-btn" onClick={() => setLang(lang === "en" ? "ar" : "en")}>{lang === "en" ? "العربية" : "English"}</button></div></header>
        <section className="chat-area">
          {active.messages.map((m) => (<div key={m.id} className={`bubble ${m.role}`}><div className="meta">{m.role} - {m.time} {m.voice ? "(voice)" : ""}</div><div>{m.text}</div></div>))}
        </section>
        <footer className="chat-input-bar"><button className={`mic-btn ${listening ? "pulse" : ""}`} onClick={startVoice}>{listening ? (lang === "ar" ? "جاري الاستماع..." : "Listening...") : (lang === "ar" ? "ابدأ الصوت" : "Start Voice")}</button><input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void onSend(); } }} placeholder={active.patient ? (lang === "ar" ? "اكتب رسالتك" : "Type your message") : (lang === "ar" ? "اكتب اسمك للبدء" : "Type your name to start")} /><button onClick={onSend}>Send</button></footer>
      </main>

      <aside className="right-panel panel">
        <section><h3>Patient Information</h3><ul className="facts"><li>Patient ID: <strong>{active.patient?.patient_code || "-"}</strong></li><li>Name: <strong>{active.patient ? `${active.patient.first_name} ${active.patient.last_name}` : "-"}</strong></li><li>Preferred Language: <strong>{lang.toUpperCase()}</strong></li><li>Status: <strong className={active.verified ? "ok" : "warn"}>{active.verified ? "Verified" : "Pending"}</strong></li></ul></section>
        <section><h3>Appointment Summary</h3><div className="confirm-card"><p><strong>Patient Name:</strong> {active.patient ? `${active.patient.first_name} ${active.patient.last_name}` : "-"}</p><p><strong>Doctor:</strong> {active.draft.doctor ? `Dr. ${active.draft.doctor.first_name} ${active.draft.doctor.last_name}` : "-"}</p><p><strong>Date:</strong> {active.draft.start ? formatDate(active.draft.start) : "-"}</p><p><strong>Time:</strong> {active.draft.start ? formatTime(active.draft.start) : "-"}</p><p><strong>Status:</strong> {active.stage === "completed" ? "Confirmed" : active.stage === "await_confirmation" ? "Pending confirmation" : "In progress"}</p></div></section>
        <section><h3>Doctor List</h3><div className="confirm-card"><p>{doctors.length ? doctors.map((d) => `Dr. ${d.first_name} ${d.last_name} (${d.specialty})`).join(", ") : "Ask in chat: show doctor list"}</p></div></section>
      </aside>
    </div>
  );
}

function ChatGroup({ title, items, active, onPick }: { title: string; items: ConversationSession[]; active: string; onPick: (id: string) => void }) {
  return (
    <div className="chat-group">
      <p className="group-title">{title}</p>
      {items.map((item) => (
        <button key={item.id} className={`chat-item ${active === item.id ? "active" : ""}`} onClick={() => onPick(item.id)}>{item.title}</button>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

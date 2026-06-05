import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import Vapi from "@vapi-ai/web";
import "./styles.css";

type Lang = "en" | "ar";
type Role = "assistant" | "user" | "system";
type Stage = "ask_name" | "ask_phone" | "ask_intent" | "ask_doctor" | "ask_datetime" | "await_confirmation" | "completed";
type Intent = "book" | "reschedule" | "cancel" | "unknown";
type VisitType = "in_person" | "virtual" | "phone";
type VoiceInputProvider = "gemini" | "browser";
type CallStatus = "idle" | "connecting" | "connected" | "ended" | "error";

type ChatMessage = {
  id: string;
  role: Role;
  text: string;
  speechText?: string;
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
  phone?: string | null;
  email?: string | null;
};

type Draft = {
  intent: Intent;
  doctor: Doctor | null;
  start: Date | null;
  pendingStart: Date | null;
  appointmentCode: string | null;
  visitType: VisitType;
  patientName: string | null;
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
    webkitAudioContext?: typeof AudioContext;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const VAPI_PUBLIC_KEY = import.meta.env.VITE_VAPI_PUBLIC_KEY ?? "";
const VAPI_ASSISTANT_ID = import.meta.env.VITE_VAPI_ASSISTANT_ID ?? "";
const STORE_KEY = "medvoice_sessions_v1";

const now = () => new Date().toLocaleTimeString();
const pad = (value: number) => String(value).padStart(2, "0");
const toDateInputValue = (value: Date) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
const toTimeInputValue = (value: Date) => `${pad(value.getHours())}:${pad(value.getMinutes())}`;

function downsampleTo16Khz(buffer: Float32Array, inputSampleRate: number): Int16Array {
  const targetSampleRate = 16000;
  if (inputSampleRate === targetSampleRate) {
    return floatTo16BitPcm(buffer);
  }

  const ratio = inputSampleRate / targetSampleRate;
  const outputLength = Math.floor(buffer.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    output[i] = buffer[Math.floor(i * ratio)] || 0;
  }
  return floatTo16BitPcm(output);
}

function floatTo16BitPcm(buffer: Float32Array): Int16Array {
  const output = new Int16Array(buffer.length);
  for (let i = 0; i < buffer.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, buffer[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function pcmChunksToBase64(chunks: Int16Array[]): string {
  const byteLength = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(new Uint8Array(chunk.buffer), offset);
    offset += chunk.byteLength;
  }

  let binary = "";
  const batchSize = 0x8000;
  for (let i = 0; i < bytes.length; i += batchSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + batchSize));
  }
  return btoa(binary);
}

function toDate(value: Date | string | null | undefined): Date | null {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const formatDate = (value: Date | string) => {
  const d = toDate(value);
  return d ? d.toLocaleDateString(undefined, { weekday: "long", day: "2-digit", month: "long", year: "numeric" }) : "-";
};
const formatTime = (value: Date | string) => {
  const d = toDate(value);
  return d ? d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "-";
};

function isQuotaError(message: string) {
  const lower = message.toLowerCase();
  return lower.includes("429") || lower.includes("quota") || lower.includes("resource_exhausted");
}

function normalizeTranscript(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  const parts = compact
    .split(/[.!?\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 2) return compact;

  const last = parts[parts.length - 1];
  const previous = parts[parts.length - 2];
  if (last.toLowerCase().startsWith(previous.toLowerCase())) return last;
  if (previous.toLowerCase().startsWith(last.toLowerCase())) return previous;
  return compact;
}

const phrases = {
  en: {
    welcome: "Welcome. I can help you book, reschedule, or cancel an appointment. May I know your full name?",
    askPhone: "Thank you. Please share your phone number so we can contact you about your appointment.",
    invalidPhone: "Please enter a valid phone number, including country code if possible. Example: +966500001234.",
    greet: (name: string) => `Thank you ${name}. How can I help you today: booking, rescheduling, or cancellation?`,
    askDoctor: "Please tell me the doctor name or department. You may also say: show doctor list.",
    chooseDoctor: "Please select a doctor by name, or tell me the department you prefer.",
    doctorListSpeech: (count: number) => `${count} doctors found. Please select one from the list.`,
    askDateTime: "Please share your preferred date and time. Example: tomorrow 10:00 AM.",
    askConfirm: (doctor: string, dt: Date, visitType: VisitType) => `I found an available ${visitType.replace("_", " ")} slot on ${formatDate(dt)} at ${formatTime(dt)} with ${doctor}. Would you like me to confirm this appointment?`,
    booked: "Your appointment has been booked successfully.",
    bookedSpeech: "Appointment booked successfully. Details are shown in the chat.",
    thanksReply: "You're welcome. If you want to book, reschedule, or cancel an appointment, please tell me and I’ll help right away.",
    clarification: "I want to make sure I understood correctly. Would you like to book, reschedule, or cancel?",
    fallback: "I’m sorry, I didn’t fully understand. I can help with booking, rescheduling, or cancellation.",
    needDoctor: "Before confirmation, please tell me the doctor or department.",
    needDateTime: "Before confirmation, please share date and time.",
    noDoctors: "I could not load doctors right now. Please try again in a moment.",
    emptyDoctors: "No doctors are available in the database yet. Please redeploy the backend or seed the database, then try again.",
    invalidDate: "I could not understand that date/time. Please try like: tomorrow 10:30 AM.",
    unavailable: "This slot is not available. I can help you choose another time.",
    askAppointmentCode: "Please share your appointment code so I can proceed.",
    cancelled: "Your appointment has been cancelled successfully.",
    rescheduled: "Your appointment has been rescheduled successfully.",
    rescheduledSpeech: "Appointment rescheduled successfully. Updated details are shown in the chat.",
    confirmCancel: "Are you sure you want to cancel this appointment?",
    goodbye: "Thank you for visiting. Wishing you good health.",
  },
  ar: {
    welcome: "مرحباً. يمكنني مساعدتك في حجز أو إعادة جدولة أو إلغاء موعد. ما اسمك الكامل؟",
    askPhone: "شكراً لك. يرجى تزويدي برقم هاتفك للتواصل معك بخصوص موعدك.",
    invalidPhone: "يرجى إدخال رقم هاتف صحيح، ويفضل أن يتضمن رمز الدولة. مثال: +966500001234.",
    greet: (name: string) => `شكراً ${name}. كيف يمكنني مساعدتك اليوم: حجز أم إعادة جدولة أم إلغاء؟`,
    askDoctor: "من فضلك اذكر اسم الطبيب أو القسم. ويمكنك قول: اعرض قائمة الأطباء.",
    chooseDoctor: "يرجى اختيار طبيب بالاسم، أو إخباري بالقسم الذي تفضله.",
    doctorListSpeech: (count: number) => `تم العثور على ${count} أطباء. يرجى اختيار طبيب من القائمة.`,
    askDateTime: "من فضلك اذكر التاريخ والوقت المناسبين. مثال: غداً 10:00 صباحاً.",
    askConfirm: (doctor: string, dt: Date, visitType: VisitType) => `وجدت موعد ${visitType.replace("_", " ")} متاحاً يوم ${formatDate(dt)} الساعة ${formatTime(dt)} مع ${doctor}. هل ترغب بتأكيد هذا الموعد؟`,
    booked: "شكراً لك. تم تأكيد موعدك بنجاح. شكراً لاختيارك عيادتنا.",
    bookedSpeech: "تم حجز الموعد بنجاح. التفاصيل ظاهرة في المحادثة.",
    thanksReply: "على الرحب والسعة. إذا رغبت بالحجز أو إعادة الجدولة أو الإلغاء، أخبرني وسأساعدك مباشرة.",
    clarification: "أريد التأكد من فهمي بشكل صحيح. هل ترغب في الحجز أم إعادة الجدولة أم الإلغاء؟",
    fallback: "عذراً، لم أفهم طلبك بالكامل. يمكنني المساعدة في الحجز أو إعادة الجدولة أو الإلغاء.",
    needDoctor: "قبل التأكيد، يرجى تحديد الطبيب أو القسم.",
    needDateTime: "قبل التأكيد، يرجى تحديد التاريخ والوقت.",
    noDoctors: "تعذر تحميل قائمة الأطباء حالياً. حاول مرة أخرى بعد قليل.",
    emptyDoctors: "لا توجد بيانات أطباء في قاعدة البيانات حالياً. يرجى إعادة نشر الخادم أو تهيئة قاعدة البيانات ثم المحاولة مرة أخرى.",
    invalidDate: "لم أتمكن من فهم التاريخ/الوقت. جرّب مثلاً: غداً 10:30 صباحاً.",
    unavailable: "هذا الموعد غير متاح. أستطيع مساعدتك في اختيار وقت آخر.",
    askAppointmentCode: "يرجى تزويدي برمز الموعد للمتابعة.",
    cancelled: "شكراً لك. تم إلغاء الموعد بنجاح.",
    rescheduled: "شكراً لك. تم إعادة جدولة الموعد بنجاح.",
    rescheduledSpeech: "تمت إعادة جدولة الموعد بنجاح. التفاصيل ظاهرة في المحادثة.",
    confirmCancel: "هل أنت متأكد أنك تريد إلغاء هذا الموعد؟",
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

function normalizePhone(input: string): string | null {
  const cleaned = input.trim().replace(/[^\d+]/g, "");
  const plus = cleaned.startsWith("+") ? "+" : "";
  const digits = cleaned.replace(/\D/g, "");
  if (digits.length < 7 || digits.length > 15) return null;
  return `${plus}${digits}`;
}

function detectIntent(text: string): { intent: Intent; confidence: number } {
  const t = text.toLowerCase();
  const has = (arr: string[]) => arr.some((k) => t.includes(k));
  if (has(["book", "appointment", "حجز", "موعد"])) return { intent: "book", confidence: 0.86 };
  if (has(["reschedule", "change", "move", "إعادة", "تغيير"])) return { intent: "reschedule", confidence: 0.84 };
  if (has(["cancel", "إلغاء"])) return { intent: "cancel", confidence: 0.82 };
  return { intent: "unknown", confidence: 0.2 };
}

function isDoctorListRequest(text: string) {
  const t = text.toLowerCase();
  return [
    "doctor list",
    "doctors list",
    "available doctors",
    "show doctor",
    "show doctors",
    "show me doctor",
    "show me doctors",
    "list doctor",
    "list doctors",
    "see doctor",
    "see doctors",
    "قائمة",
    "الأطباء",
    "الاطباء",
    "اعرض",
  ].some((k) => t.includes(k));
}

function isThanks(text: string) {
  const t = text.toLowerCase();
  return ["thanks", "thank you", "appreciate", "شكرا", "شكراً"].some((k) => t.includes(k));
}

function isConfirm(text: string) {
  const t = text.toLowerCase();
  return ["yes", "confirm", "go ahead", "book it", "تأكيد", "نعم", "موافق"].some((k) => t.includes(k));
}

function isReject(text: string) {
  const t = text.toLowerCase();
  return ["no", "not now", "cancel", "stop", "لا", "كلا"].some((k) => t.includes(k));
}

function parseAppointmentCode(text: string): string | null {
  const match = text.match(/apt[-\s]?[a-z0-9]{4,}/i);
  return match ? match[0].toUpperCase().replace(" ", "-") : null;
}

function parseDateTime(text: string): Date | null {
  const lower = text.toLowerCase().replace(/\btomm?orow\b/g, "tomorrow").replace(/\s+/g, " ").trim();
  const nowDate = new Date();
  let base = new Date(nowDate);
  let hasDateSignal = false;
  let defaultHour: number | null = null;

  if (/\btoday\b|اليوم/.test(lower)) hasDateSignal = true;
  if (/\btomorrow\b|غد/.test(lower)) {
    base.setDate(base.getDate() + 1);
    hasDateSignal = true;
  }
  if (/\bnext week\b/.test(lower)) {
    base.setDate(base.getDate() + 7);
    hasDateSignal = true;
  }

  if (/\bmorning\b|صباح/.test(lower)) defaultHour = 9;
  if (/\bafternoon\b|بعد الظهر/.test(lower)) defaultHour = 14;
  if (/\bevening\b|مساء/.test(lower)) defaultHour = 17;
  if (/\bnight\b|ليلاً|ليلا/.test(lower)) defaultHour = 19;
  if (/\bnoon\b/.test(lower)) defaultHour = 12;

  const monthMap: Record<string, number> = {
    jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3, may: 4, jun: 5, june: 5,
    jul: 6, july: 6, aug: 7, august: 7, sep: 8, sept: 8, september: 8, oct: 9, october: 9, nov: 10, november: 10, dec: 11, december: 11,
  };
  const weekdayMap: Record<string, number> = {
    sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, tues: 2, wednesday: 3, wed: 3,
    thursday: 4, thu: 4, thurs: 4, friday: 5, fri: 5, saturday: 6, sat: 6,
  };

  // Examples: 28th May, 28th of May, 30 May 2026
  const explicit = lower.match(/(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+([a-z]{3,9})(?:\s*,?\s*(\d{4}))?/i);
  if (explicit) {
    const day = Number(explicit[1]);
    const month = monthMap[explicit[2].toLowerCase()];
    if (month !== undefined) {
      const year = explicit[3] ? Number(explicit[3]) : base.getFullYear();
      base = new Date(year, month, day, 0, 0, 0, 0);
      if (!explicit[3] && base < nowDate) base.setFullYear(base.getFullYear() + 1);
      hasDateSignal = true;
    }
  }

  const dateMatch = lower.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (dateMatch) {
    base = new Date(`${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}T00:00:00`);
    hasDateSignal = true;
  }

  const weekdayMatch = lower.match(/\b(next\s+)?(sun(?:day)?|mon(?:day)?|tue(?:s|sday|day)?|wed(?:nesday)?|thu(?:rs|rsday|rday)?|fri(?:day)?|sat(?:urday)?)\b/i);
  if (weekdayMatch) {
    const dayName = weekdayMatch[2].toLowerCase();
    const target = weekdayMap[dayName] ?? weekdayMap[`${dayName}day`];
    if (target !== undefined) {
      const current = nowDate.getDay();
      let diff = (target - current + 7) % 7;
      if (diff === 0) diff = 7;
      base = new Date(nowDate);
      base.setDate(nowDate.getDate() + diff);
      base.setHours(0, 0, 0, 0);
      hasDateSignal = true;
    }
  }

  const timeMatch =
    lower.match(/(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i) ||
    lower.match(/\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i) ||
    (!explicit && !dateMatch && lower.match(/\b(\d{1,2})(?::(\d{2}))?\b/i));

  if (timeMatch) {
    let h = Number(timeMatch[1]);
    const m = Number(timeMatch[2] || 0);
    const meridian = (timeMatch[3] || "").toLowerCase();
    if (meridian === "pm" && h < 12) h += 12;
    if (meridian === "am" && h === 12) h = 0;
    if (!meridian && h >= 1 && h <= 7 && (defaultHour === 17 || lower.includes("evening"))) h += 12;
    if (h > 23 || m > 59) return null;
    base.setHours(h, m, 0, 0);
  } else if (defaultHour !== null && hasDateSignal) {
    base.setHours(defaultHour, 0, 0, 0);
  } else if (defaultHour !== null) {
    base.setHours(defaultHour, 0, 0, 0);
    if (base < nowDate) base.setDate(base.getDate() + 1);
  } else {
    return null;
  }

  if (!hasDateSignal && base < nowDate) base.setDate(base.getDate() + 1);
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
    draft: { intent: "unknown", doctor: null, start: null, pendingStart: null, appointmentCode: null, visitType: "in_person", patientName: null },
    summary: "",
  };
}

function normalizeSession(value: unknown): ConversationSession | null {
  if (!value || typeof value !== "object") return null;
  const session = value as Partial<ConversationSession>;
  const draft = session.draft ?? {};
  return {
    id: typeof session.id === "string" ? session.id : crypto.randomUUID(),
    title: typeof session.title === "string" ? session.title : "New Conversation",
    createdAt: typeof session.createdAt === "number" ? session.createdAt : Date.now(),
    messages: Array.isArray(session.messages) ? session.messages : [],
    stage: session.stage ?? "ask_name",
    patient: session.patient ?? null,
    verified: Boolean(session.verified),
    draft: {
      intent: draft.intent ?? "unknown",
      doctor: draft.doctor ?? null,
      start: toDate(draft.start),
      pendingStart: toDate(draft.pendingStart),
      appointmentCode: draft.appointmentCode ?? null,
      visitType: draft.visitType ?? "in_person",
      patientName: draft.patientName ?? null,
    },
    summary: typeof session.summary === "string" ? session.summary : "",
  };
}

function doctorAppointmentDetails(doctor: Doctor, start: Date, visitType: VisitType, code?: string | null) {
  return [
    `Doctor: Dr. ${doctor.first_name} ${doctor.last_name}`,
    `Date: ${formatDate(start)}`,
    `Time: ${formatTime(start)}`,
    `Appointment type: ${visitType.replace("_", " ")}`,
    code ? `Appointment code: ${code}` : "",
  ].filter(Boolean).join("\n");
}

function appointmentStatusLabel(session: ConversationSession): string {
  if (session.stage === "completed" && session.draft.intent === "cancel") return "Cancelled";
  if (session.stage === "completed") return "Confirmed";
  if (session.stage === "await_confirmation") return "Pending confirmation";
  if (session.summary === "confirmed_coming") return "Confirmed coming";
  if (session.summary === "rescheduled") return "Rescheduled";
  return "In progress";
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
  const [voiceInputProvider, setVoiceInputProvider] = useState<VoiceInputProvider>("gemini");
  const [callStatus, setCallStatus] = useState<CallStatus>("idle");
  const [playingMessageId, setPlayingMessageId] = useState<string | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [pickerDate, setPickerDate] = useState(() => toDateInputValue(new Date()));
  const [pickerTime, setPickerTime] = useState("09:00");
  const playbackRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const voiceReplyPendingRef = useRef(false);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pcmChunksRef = useRef<Int16Array[]>([]);
  const vapiRef = useRef<any>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as unknown;
        const restored = Array.isArray(parsed) ? parsed.map(normalizeSession).filter((s): s is ConversationSession => Boolean(s)) : [];
        if (restored.length) {
          setSessions(restored);
          setActiveId(restored[0].id);
          return;
        }
      } catch {
        localStorage.removeItem(STORE_KEY);
      }
    }
    const first = mkNewSession("en");
    setSessions([first]);
    setActiveId(first.id);
  }, []);

  useEffect(() => {
    if (sessions.length) localStorage.setItem(STORE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    return () => {
      playbackRef.current?.pause();
      if (playbackRef.current?.src) URL.revokeObjectURL(playbackRef.current.src);
      recognitionRef.current?.abort();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
      vapiRef.current?.stop?.();
    };
  }, []);

  const active = sessions.find((s) => s.id === activeId) || sessions[0];

  const updateActive = (mutator: (s: ConversationSession) => ConversationSession) => {
    setSessions((prev) => prev.map((s) => (s.id === activeId ? mutator(s) : s)));
  };

  const addMsg = (role: Role, text: string, voice = false, speechText?: string) => {
    const message: ChatMessage = { id: crypto.randomUUID(), role, text, speechText, time: now(), voice };
    let appended = false;
    updateActive((s) => {
      const last = s.messages[s.messages.length - 1];
      if (last?.role === role && last.text === text) return s;
      appended = true;
      return { ...s, messages: [...s.messages, message] };
    });
    if (role === "assistant" && voiceReplyPendingRef.current) {
      voiceReplyPendingRef.current = false;
      if (appended) window.setTimeout(() => void playAssistantMessage(message), 100);
    }
    return message;
  };

  const getVapiClient = () => {
    if (!VAPI_PUBLIC_KEY || !VAPI_ASSISTANT_ID) {
      addMsg("system", "Vapi call is not configured. Set VITE_VAPI_PUBLIC_KEY and VITE_VAPI_ASSISTANT_ID in .env, then restart the frontend.");
      return null;
    }
    if (vapiRef.current) return vapiRef.current;

    const client = new Vapi(VAPI_PUBLIC_KEY);
    client.on("call-start", () => {
      setCallStatus("connected");
      addMsg("system", "Medical center call connected.");
    });
    client.on("call-end", () => {
      setCallStatus("ended");
      addMsg("system", "Medical center call ended.");
    });
    client.on("error", (error: unknown) => {
      setCallStatus("error");
      const message = error instanceof Error ? error.message : "Vapi call failed.";
      addMsg("system", message);
    });
    vapiRef.current = client;
    return client;
  };

  const toggleMedicalCenterCall = async () => {
    if (callStatus === "connecting") return;
    const client = getVapiClient();
    if (!client) {
      setCallStatus("error");
      return;
    }
    if (callStatus === "connected") {
      client.stop();
      return;
    }

    try {
      setCallStatus("connecting");
      await client.start(VAPI_ASSISTANT_ID, {
        metadata: {
          language: lang,
          patientId: active?.patient?.id,
          patientPhone: active?.patient?.phone,
        },
      });
    } catch (error) {
      setCallStatus("error");
      addMsg("system", error instanceof Error ? error.message : "Unable to start the Vapi call.");
    }
  };

  const playAssistantMessage = async (message: ChatMessage) => {
    if (playingMessageId === message.id) {
      playbackRef.current?.pause();
      setPlayingMessageId(null);
      return;
    }

    try {
      playbackRef.current?.pause();
      if (playbackRef.current?.src) URL.revokeObjectURL(playbackRef.current.src);

      setPlayingMessageId(message.id);
      const res = await fetch(`${API_BASE}/api/v1/realtime/speech`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: message.speechText || message.text }),
      });
      if (!res.ok) {
        let detail = "Gemini voice playback is unavailable right now.";
        try {
          const errorBody = await res.json();
          detail = typeof errorBody?.detail === "string" ? errorBody.detail : detail;
        } catch {
          // Keep the friendly fallback when the server does not return JSON.
        }
        throw new Error(detail);
      }

      const audioUrl = URL.createObjectURL(await res.blob());
      const audio = new Audio(audioUrl);
      playbackRef.current = audio;
      audio.onended = () => setPlayingMessageId(null);
      audio.onerror = () => setPlayingMessageId(null);
      await audio.play();
    } catch (error) {
      setPlayingMessageId(null);
      addMsg("system", error instanceof Error ? error.message : "Gemini voice playback is unavailable right now.");
    }
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
      if (!res.ok) throw new Error("doctor search failed");
      const data = await res.json();
      const list = Array.isArray(data) ? data : [];
      setDoctors(list);
      if (!list.length) addMsg("assistant", p.emptyDoctors);
      return list;
    } catch {
      addMsg("assistant", p.noDoctors);
      return [];
    }
  };

  const identifyPatient = async (nameRaw: string, phone: string) => {
    const name = extractName(nameRaw);
    const res = await fetch(`${API_BASE}/api/v1/patients/identify-or-create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: name, preferred_language: lang, phone }),
    });
    const data = await res.json();
    updateActive((s) => ({ ...s, patient: data.patient, verified: true, title: `${data.patient.first_name} ${data.patient.last_name}` }));
    addMsg("assistant", p.greet(`${data.patient.first_name} ${data.patient.last_name}`));
    updateActive((s) => ({ ...s, stage: "ask_intent" }));
  };

  const checkSlotAvailability = async (doctorId: number, start: Date) => {
    const end = new Date(start.getTime() + 30 * 60 * 1000);
    const res = await fetch(`${API_BASE}/api/v1/appointments/availability`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doctor_id: doctorId,
        scheduled_start: start.toISOString(),
        scheduled_end: end.toISOString(),
      }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return Boolean(data?.available);
  };

  const proposeSlot = async (dt: Date) => {
    if (!active?.draft?.doctor) {
      addMsg("assistant", p.needDoctor);
      return;
    }

    const available = await checkSlotAvailability(active.draft.doctor.id, dt);
    if (!available) {
      addMsg("assistant", p.unavailable);
      return;
    }

    const doctor = `Dr. ${active.draft.doctor.first_name} ${active.draft.doctor.last_name}`;
    const message = p.askConfirm(doctor, dt, active.draft.visitType);
    updateActive((s) => ({ ...s, draft: { ...s.draft, pendingStart: dt }, summary: message, stage: "await_confirmation" }));
    addMsg("assistant", message);
  };

  const runAppointmentAction = async (confirm: boolean, naturalText: string) => {
    if (!active?.patient) {
      addMsg("assistant", p.fallback);
      return;
    }

    if (active.draft.intent === "cancel") {
      if (!active.draft.appointmentCode) {
        addMsg("assistant", p.askAppointmentCode);
        return;
      }
      if (!confirm) {
        addMsg("assistant", p.confirmCancel);
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

    const scheduledStart = active.draft.pendingStart ?? active.draft.start ?? null;
    if (!active.draft.doctor || !scheduledStart) {
      addMsg("assistant", !active.draft.doctor ? p.needDoctor : p.needDateTime);
      return;
    }

    if (!confirm) {
      await proposeSlot(scheduledStart);
      return;
    }

    const available = await checkSlotAvailability(active.draft.doctor.id, scheduledStart);
    if (!available) {
      addMsg("assistant", p.unavailable);
      return;
    }

    const end = new Date(scheduledStart.getTime() + 30 * 60 * 1000);

    if (active.draft.intent === "book") {
      const res = await fetch(`${API_BASE}/api/v1/appointments/book`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          patient_id: active.patient.id,
          doctor_id: active.draft.doctor.id,
          scheduled_start: scheduledStart.toISOString(),
          scheduled_end: end.toISOString(),
          visit_type: active.draft.visitType,
          reason: naturalText || "Consultation",
          confirmation: true,
        }),
      });
      const data = await res.json();
      if (res.ok && data?.success) {
        const code = data?.appointment?.appointment_code || null;
        updateActive((s) => ({ ...s, stage: "completed", draft: { ...s.draft, start: scheduledStart, pendingStart: null, appointmentCode: code } }));
        addMsg("assistant", `${p.booked}\n${doctorAppointmentDetails(active.draft.doctor, scheduledStart, active.draft.visitType, code)}`, false, p.bookedSpeech);
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
          scheduled_start: scheduledStart.toISOString(),
          scheduled_end: end.toISOString(),
          confirmation: true,
        }),
      });
      if (res.ok) {
        updateActive((s) => ({ ...s, stage: "completed", draft: { ...s.draft, start: scheduledStart, pendingStart: null } }));
        addMsg("assistant", `${p.rescheduled}\n${doctorAppointmentDetails(active.draft.doctor, scheduledStart, active.draft.visitType, active.draft.appointmentCode)}`, false, p.rescheduledSpeech);
      } else {
        addMsg("assistant", p.unavailable);
      }
      return;
    }
  };

  const handleText = async (text: string, voice = false) => {
    const cleanText = voice ? normalizeTranscript(text) : text.trim();
    if (!cleanText.trim()) return;
    addMsg("user", cleanText, voice);
    voiceReplyPendingRef.current = voice;

    if (!active) return;

    const codeInMessage = parseAppointmentCode(cleanText);
    if (codeInMessage) {
      updateActive((s) => ({ ...s, draft: { ...s.draft, appointmentCode: codeInMessage } }));
      addMsg("assistant", `Appointment code ${codeInMessage} recorded.`);
    }

    const globalIntent = detectIntent(cleanText);
    if (globalIntent.confidence >= 0.55 && globalIntent.intent !== "unknown") {
      updateActive((s) => ({
        ...s,
        draft: { ...s.draft, intent: globalIntent.intent, pendingStart: null },
        stage: globalIntent.intent === "cancel" ? "await_confirmation" : s.stage === "ask_intent" ? "ask_doctor" : s.stage,
      }));
      if (globalIntent.intent === "cancel") {
        addMsg("assistant", active?.draft?.appointmentCode || codeInMessage ? p.confirmCancel : p.askAppointmentCode);
        return;
      }
      if (active?.stage === "ask_intent") {
        addMsg("assistant", p.askDoctor);
        return;
      }
    }

    if (isThanks(cleanText)) {
      addMsg("assistant", p.thanksReply);
      return;
    }

    if (["bye", "goodbye", "exit", "مع السلامة", "خروج"].some((k) => cleanText.toLowerCase().includes(k))) {
      addMsg("assistant", p.goodbye);
      return;
    }

    if (active.stage === "ask_name") {
      const name = extractName(cleanText);
      updateActive((s) => ({ ...s, draft: { ...s.draft, patientName: name }, stage: "ask_phone" }));
      addMsg("assistant", p.askPhone);
      return;
    }

    if (active.stage === "ask_phone") {
      const phone = normalizePhone(cleanText);
      if (!phone || !active.draft.patientName) {
        addMsg("assistant", p.invalidPhone);
        return;
      }
      await identifyPatient(active.draft.patientName, phone);
      return;
    }

    if (active.stage === "ask_intent") {
      const intentRes = detectIntent(cleanText);
      if (intentRes.confidence < 0.55 || intentRes.intent === "unknown") {
        addMsg("assistant", p.clarification);
        return;
      }
      updateActive((s) => ({ ...s, draft: { ...s.draft, intent: intentRes.intent }, stage: "ask_doctor" }));
      addMsg("assistant", p.askDoctor);
      return;
    }

    if (active.stage === "ask_doctor") {
      if (isDoctorListRequest(cleanText)) {
        const list = doctors.length ? doctors : await fetchDoctors();
        if (list.length) {
          addMsg("assistant", `${list.map((d) => `Dr. ${d.first_name} ${d.last_name} (${d.specialty})`).join("\n")}\n\n${p.chooseDoctor}`, false, p.doctorListSpeech(list.length));
        }
        return;
      }

      const list = doctors.length ? doctors : await fetchDoctors();
      const lower = cleanText.toLowerCase();
      const doctor = list.find((d) => {
        const full = `${d.first_name} ${d.last_name}`.toLowerCase();
        return lower.includes(full) || lower.includes(d.specialty.toLowerCase());
      });
      if (!doctor) {
        addMsg("assistant", p.needDoctor);
        return;
      }

      updateActive((s) => ({ ...s, draft: { ...s.draft, doctor, pendingStart: null }, stage: "ask_datetime" }));
      addMsg("assistant", p.askDateTime);
      return;
    }

    if (active.stage === "ask_datetime") {
      const dt = parseDateTime(cleanText);
      if (!dt) {
        addMsg("assistant", p.invalidDate);
        return;
      }
      await proposeSlot(dt);
      return;
    }

    if (active.stage === "await_confirmation") {
      if (isReject(cleanText)) {
        updateActive((s) => ({ ...s, stage: s.draft.intent === "cancel" ? "completed" : "ask_datetime", draft: { ...s.draft, pendingStart: null } }));
        addMsg("assistant", active.draft.intent === "cancel" ? "No problem. I kept the appointment as is." : p.askDateTime);
        return;
      }
      if (!isConfirm(cleanText)) {
        addMsg("assistant", p.clarification);
        return;
      }
      await runAppointmentAction(true, cleanText);
      return;
    }

    if (active.stage === "completed") {
      const i = detectIntent(cleanText);
      if (i.intent === "unknown") {
        addMsg("assistant", p.thanksReply);
        return;
      }
      updateActive((s) => ({ ...s, draft: { ...s.draft, intent: i.intent, pendingStart: null }, stage: i.intent === "cancel" ? "await_confirmation" : i.intent === "reschedule" ? "ask_datetime" : "ask_doctor" }));
      addMsg("assistant", i.intent === "cancel" ? (active.draft.appointmentCode ? p.confirmCancel : p.askAppointmentCode) : i.intent === "reschedule" ? p.askDateTime : p.askDoctor);
      return;
    }

    addMsg("assistant", p.fallback);
  };

  const stopVoiceRecording = async () => {
    processorRef.current?.disconnect();
    sourceRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    await audioContextRef.current?.close();
    processorRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
    audioContextRef.current = null;
    setListening(false);
    setVoiceMode("transcribing");

    const audioBase64 = pcmChunksToBase64(pcmChunksRef.current);
    pcmChunksRef.current = [];
    if (!audioBase64) {
      setVoiceMode("idle");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/v1/realtime/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_base64: audioBase64, mime_type: "audio/pcm;rate=16000" }),
      });
      if (!res.ok) {
        const errorBody = await res.json().catch(() => null);
        throw new Error(typeof errorBody?.detail === "string" ? errorBody.detail : "Gemini voice transcription failed.");
      }
      const data = await res.json();
      const transcript = typeof data?.transcript === "string" ? data.transcript.trim() : "";
      setVoiceMode("ready");
      if (transcript) await handleText(transcript, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Gemini voice transcription failed.";
      setVoiceMode("error");
      if (isQuotaError(message)) {
        setVoiceInputProvider("browser");
        addMsg("system", "Gemini transcription quota is exhausted. I switched voice input to browser speech recognition. Please click Start Voice again.");
        return;
      }
      addMsg("system", message);
    }
  };

  const startBrowserSpeechRecognition = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      addMsg("system", "Gemini transcription quota is exhausted, and browser speech recognition is not supported here. Please type your message.");
      setVoiceMode("error");
      return;
    }

    const rec = new SR();
    rec.lang = lang === "ar" ? "ar-SA" : "en-US";
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onstart = () => {
      setListening(true);
      setVoiceMode("browser-stt");
    };
    rec.onend = () => {
      setListening(false);
      setVoiceMode("idle");
    };
    rec.onerror = () => {
      setListening(false);
      setVoiceMode("error");
    };
    rec.onresult = async (e: SpeechRecognitionEvent) => {
      const r = e.results[e.results.length - 1];
      const txt = r[0].transcript.trim();
      if (r.isFinal && txt) {
        rec.stop();
        await handleText(txt, true);
      }
    };
    recognitionRef.current = rec;
    rec.start();
  };

  const startVoice = async () => {
    if (listening) {
      if (voiceInputProvider === "browser") {
        recognitionRef.current?.stop();
        return;
      }
      await stopVoiceRecording();
      return;
    }

    if (voiceInputProvider === "browser") {
      startBrowserSpeechRecognition();
      return;
    }

    setVoiceMode("connecting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextCtor();
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      pcmChunksRef.current = [];
      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        pcmChunksRef.current.push(downsampleTo16Khz(input, audioContext.sampleRate));
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
      streamRef.current = stream;
      audioContextRef.current = audioContext;
      sourceRef.current = source;
      processorRef.current = processor;
      setVoiceMode("ready");
      setListening(true);
    } catch (error) {
      setVoiceMode("error");
      addMsg("system", error instanceof Error ? error.message : "Microphone access is unavailable.");
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

  const submitPickerValue = async () => {
    const selected = new Date(`${pickerDate}T${pickerTime || "09:00"}:00`);
    if (Number.isNaN(selected.getTime())) {
      addMsg("assistant", p.invalidDate);
      return;
    }
    addMsg("user", `${formatDate(selected)} at ${formatTime(selected)}`);
    await proposeSlot(selected);
  };

  const startReschedule = () => {
    const base = active.draft.start ?? new Date();
    setPickerDate(toDateInputValue(base));
    setPickerTime(toTimeInputValue(base));
    updateActive((s) => ({ ...s, stage: "ask_datetime", draft: { ...s.draft, intent: "reschedule", pendingStart: null } }));
    addMsg("assistant", p.askDateTime);
  };

  const startCancel = () => {
    updateActive((s) => ({ ...s, stage: "await_confirmation", draft: { ...s.draft, intent: "cancel", pendingStart: null } }));
    addMsg("assistant", active.draft.appointmentCode ? p.confirmCancel : p.askAppointmentCode);
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
        <header className="chat-header"><div><h2>MediAssist AI</h2><span className="online">Online</span></div><div className="header-tools"><button className={`call-center-btn ${callStatus === "connected" ? "active" : ""}`} onClick={() => void toggleMedicalCenterCall()} disabled={callStatus === "connecting"} title={callStatus === "connected" ? "End medical center call" : "Call medical center"} aria-label={callStatus === "connected" ? "End medical center call" : "Call medical center"}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8c1.6 3.1 4.1 5.6 7.2 7.2l2.4-2.4c.3-.3.8-.4 1.2-.3 1.3.4 2.6.6 4 .6.7 0 1.2.5 1.2 1.2v3.8c0 .7-.5 1.2-1.2 1.2C10.7 22.1 2 13.4 2 2.6 2 1.9 2.5 1.4 3.2 1.4H7c.7 0 1.2.5 1.2 1.2 0 1.4.2 2.7.6 4 .1.4 0 .8-.3 1.2l-2.4 2.4Z" /></svg><span>{callStatus === "connected" ? "End call" : callStatus === "connecting" ? "Calling..." : "Call center"}</span></button><span>Language: {lang.toUpperCase()}</span><span>Voice mode: {voiceMode}</span><span>Input: {voiceInputProvider === "gemini" ? "Gemini" : "Browser"}</span><button className="lang-btn" onClick={() => setLang(lang === "en" ? "ar" : "en")}>{lang === "en" ? "العربية" : "English"}</button></div></header>
        <section className="chat-area">
          {active.messages.map((m) => (<div key={m.id} className={`bubble ${m.role}`}><div className="bubble-head"><div className="meta">{m.role} - {m.time} {m.voice ? "(voice transcript)" : ""}</div>{m.role === "assistant" && (<button className="play-reply-btn" onClick={() => void playAssistantMessage(m)} title="Play Gemini Live assistant reply" aria-label="Play Gemini Live assistant reply">{playingMessageId === m.id ? "Stop" : "Play"}</button>)}</div><div className="message-text">{m.text}</div></div>))}
          {active.stage === "ask_datetime" && active.draft.doctor && (
            <DateTimePicker
              date={pickerDate}
              time={pickerTime}
              onDate={setPickerDate}
              onTime={setPickerTime}
              onSubmit={submitPickerValue}
            />
          )}
        </section>
        <footer className="chat-input-bar"><button className={`mic-btn ${listening ? "pulse" : ""}`} onClick={startVoice}>{listening ? (lang === "ar" ? "إيقاف التسجيل" : "Stop Recording") : (lang === "ar" ? "ابدأ الصوت" : "Start Voice")}</button><input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void onSend(); } }} placeholder={active.patient ? (lang === "ar" ? "اكتب رسالتك" : "Type your message") : (lang === "ar" ? "اكتب اسمك للبدء" : "Type your name to start")} /><button onClick={onSend}>Send</button></footer>
      </main>

      <aside className="right-panel panel">
        <section><h3>Patient Information</h3><ul className="facts"><li>Patient ID: <strong>{active.patient?.patient_code || "-"}</strong></li><li>Name: <strong>{active.patient ? `${active.patient.first_name} ${active.patient.last_name}` : "-"}</strong></li><li>Phone: <strong>{active.patient?.phone || "-"}</strong></li><li>Preferred Language: <strong>{lang.toUpperCase()}</strong></li><li>Status: <strong className={active.verified ? "ok" : "warn"}>{active.verified ? "Verified" : "Pending"}</strong></li></ul></section>
        <section><h3>Appointment Summary</h3><div className="confirm-card"><p><strong>Patient Name:</strong> {active.patient ? `${active.patient.first_name} ${active.patient.last_name}` : "-"}</p><p><strong>Doctor:</strong> {active.draft.doctor ? `Dr. ${active.draft.doctor.first_name} ${active.draft.doctor.last_name}` : "-"}</p><p><strong>Date:</strong> {active.draft.start ? formatDate(active.draft.start) : "-"}</p><p><strong>Time:</strong> {active.draft.start ? formatTime(active.draft.start) : "-"}</p><p><strong>Appointment type:</strong> {active.draft.visitType.replace("_", " ")}</p><p><strong>Code:</strong> {active.draft.appointmentCode || "-"}</p><p><strong>Status:</strong> {appointmentStatusLabel(active)}</p>{active.stage === "completed" && active.draft.appointmentCode && active.draft.intent !== "cancel" && (<div className="summary-actions"><button onClick={startReschedule}>Reschedule</button><button className="danger-btn" onClick={startCancel}>Cancel Appointment</button></div>)}</div></section>
        {active.stage === "ask_datetime" && active.draft.doctor && (
          <section><h3>Pick Date & Time</h3><DateTimePicker date={pickerDate} time={pickerTime} onDate={setPickerDate} onTime={setPickerTime} onSubmit={submitPickerValue} compact /></section>
        )}
        <section><h3>Doctor List</h3><div className="confirm-card"><p>{doctors.length ? doctors.map((d) => `Dr. ${d.first_name} ${d.last_name} (${d.specialty})`).join(", ") : "Ask in chat: show doctor list"}</p></div></section>
      </aside>
    </div>
  );
}

function DateTimePicker({ date, time, onDate, onTime, onSubmit, compact = false }: { date: string; time: string; onDate: (value: string) => void; onTime: (value: string) => void; onSubmit: () => void; compact?: boolean }) {
  return (
    <div className={`datetime-picker ${compact ? "compact" : ""}`}>
      <div>
        <label>Date</label>
        <input type="date" value={date} onChange={(e) => onDate(e.target.value)} />
      </div>
      <div>
        <label>Time</label>
        <input type="time" value={time} onChange={(e) => onTime(e.target.value)} />
      </div>
      <button onClick={onSubmit}>Use this slot</button>
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

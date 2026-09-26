export type Role = "patient" | "doctor" | "nurse" | "admin";

export interface Session {
  token: string;
  role: Role;
  name: string;
  patientId: number | null;
}

export interface Source {
  id: string;
  title: string;
  refs?: string[];
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  tool_calls: { name: string; ok: boolean; error: string | null }[];
  events: string[];
  emergency: string[];
  usage: { prompt_tokens?: number; completion_tokens?: number };
  model: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  meta?: Omit<ChatResponse, "answer">;
  error?: boolean;
}

export interface PatientLite {
  id: number;
  name: string;
  birth_year: number;
  sex: string;
}

export interface PatientProfile extends PatientLite {
  allergies?: string;
  medications?: string;
}

export interface Intake {
  id: number;
  text: string;
  created_at: string;
  allergies: string | null;
  medications: string | null;
}

export interface Encounter {
  id: number;
  visit_date: string;
  chief_complaint: string;
  notes: string;
}

export interface Appointment {
  id: number;
  patient_id: number;
  patient_name: string;
  doctor_name: string;
  slot: string;
  reason: string;
  status: string;
}

export interface SoapNote {
  id: number;
  encounter_id: number;
  patient_id: number;
  patient_name: string;
  visit_date: string;
  chief_complaint: string;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  status: "draft" | "approved";
  created_at: string;
}

export interface AuditRow {
  id: number;
  ts: string;
  user_id: number | null;
  role: string | null;
  action: string;
  detail: string | null;
}

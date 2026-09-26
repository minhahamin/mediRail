export type Role = "patient" | "doctor" | "nurse" | "admin" | "superadmin";

export interface Session {
  token: string;
  role: Role;
  name: string;
  patientId: number | null;
  readOnly?: boolean;   // 읽기 전용 관리자(공개 데모)
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

export interface DemoAccount {
  username: string;
  role: Role;
  name: string;
}

export interface AdminUser {
  id: number;
  username: string;
  role: Role;
  name: string;
  patient_id: number | null;
  read_only: boolean;
  disabled: boolean;
  is_demo: boolean;
}

export interface AdminStats {
  users_by_role: Record<string, number>;
  users: number;
  users_capacity: number;
  disabled_users: number;
  patients: number;
  appointments_booked: number;
  soap_draft: number;
  soap_approved: number;
  audit_entries: number;
  security_events: number;
  break_glass_events: number;
  ai_requests_today: number;
  ai_requests_limit: number;
  model: string;
}

export interface BreakGlassResult {
  patient: { id: number; name: string; birth_year: number; sex: string; allergies: string; medications: string };
  intake: { id: number; text: string; created_at: string } | null;
  encounters: Encounter[];
  soap_notes: { id: number; encounter_id: number; subjective: string; objective: string; assessment: string; plan: string; status: "draft" | "approved"; created_at: string }[];
  notice: string;
}

import type {
  AdminStats, AdminUser, Appointment, AuditRow, BreakGlassResult, ChatResponse, DemoAccount, Encounter, Intake, PatientLite, PatientProfile, Session, SoapNote,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let token: string | null = null;
let onUnauthorized: () => void = () => {};

export function setToken(t: string | null) {
  token = t;
}

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  }
  if (res.status === 401 && token) onUnauthorized();
  if (!res.ok) {
    let detail = `요청에 실패했습니다 (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* 본문이 JSON이 아니면 기본 메시지 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  demoAccounts: () => request<DemoAccount[]>("/auth/demo-accounts"),
  register: async (body: { username: string; password: string; name: string; birth_year: number; sex: "F" | "M"; allergies: string; medications: string }): Promise<Session> => {
    const r = await post<{ access_token: string; role: Session["role"]; name: string; patient_id: number | null; read_only?: boolean }>("/auth/register", body);
    return { token: r.access_token, role: r.role, name: r.name, patientId: r.patient_id, readOnly: !!r.read_only };
  },
  login: async (username: string, password: string): Promise<Session> => {
    const r = await post<{ access_token: string; role: Session["role"]; name: string; patient_id: number | null; read_only?: boolean }>("/auth/login", { username, password });
    return { token: r.access_token, role: r.role, name: r.name, patientId: r.patient_id, readOnly: !!r.read_only };
  },
  chat: (message: string, history: { role: string; content: string }[], patientId: number | null) =>
    post<ChatResponse>("/chat", { message, history, patient_id: patientId }),
  patients: () => request<PatientLite[]>("/patients"),
  patient: (id: number) => request<PatientProfile>(`/patients/${id}`),
  intake: (id: number) => request<Intake | null>(`/patients/${id}/intake`),
  encounters: (id: number) => request<Encounter[]>(`/patients/${id}/encounters`),
  appointments: () => request<Appointment[]>("/appointments"),
  slots: (date: string) => request<{ date: string; slots: string[] }>(`/appointments/slots?date=${date}`),
  book: (slot: string, reason: string, patientId?: number) => post<{ appointment_id: number; slot: string; doctor_name: string }>("/appointments", { slot, reason, patient_id: patientId ?? null }),
  cancel: (id: number) => request<{ status: string }>(`/appointments/${id}`, { method: "DELETE" }),
  soaps: (status?: string) => request<SoapNote[]>(`/soap${status ? `?status=${status}` : ""}`),
  approve: (id: number) => post<{ status: string }>(`/soap/${id}/approve`),
  audit: () => request<AuditRow[]>("/audit?limit=200"),
  me: () => request<{ id: number; username: string; role: string }>("/me"),
  adminUsers: () => request<AdminUser[]>("/admin/users"),
  setRole: (id: number, role: string) => request<{ changed: boolean }>(`/admin/users/${id}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
  disableUser: (id: number) => post<{ disabled: boolean }>(`/admin/users/${id}/disable`),
  enableUser: (id: number) => post<{ disabled: boolean }>(`/admin/users/${id}/enable`),
  adminStats: () => request<AdminStats>("/admin/stats"),
  breakGlass: (patientId: number, reason: string) => post<BreakGlassResult>("/admin/break-glass", { patient_id: patientId, reason }),
};

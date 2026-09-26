import { useCallback, useEffect, useState } from "react";
import { api, setToken, setUnauthorizedHandler } from "./api";
import { Appointments } from "./components/Appointments";
import { AdminStatsView, AdminUsers, BreakGlass } from "./components/Admin";
import { Audit } from "./components/Audit";
import { Chat } from "./components/Chat";
import { Demo, Login, Signup } from "./components/Auth";
import { Patients } from "./components/Patients";
import { Soap } from "./components/Soap";
import { Icon, type IconName } from "./components/Icon";
import { ROLE_ICON, ROLE_LABEL, Sparkle, TrafficLights } from "./components/ui";
import { navigate, useAuthRoute } from "./router";
import type { PatientLite, Role, Session } from "./types";

type TabId = "chat" | "appointments" | "patients" | "soap" | "audit" | "users" | "stats" | "breakglass";

const TABS: Record<Role, { id: TabId; label: string; icon: IconName }[]> = {
  patient: [{ id: "chat", label: "상담", icon: "chat" }, { id: "appointments", label: "내 예약", icon: "calendar" }],
  nurse: [{ id: "chat", label: "상담", icon: "chat" }, { id: "patients", label: "환자", icon: "patients" }, { id: "appointments", label: "예약 현황", icon: "calendar" }],
  doctor: [{ id: "chat", label: "상담", icon: "chat" }, { id: "patients", label: "환자", icon: "patients" }, { id: "soap", label: "SOAP", icon: "soap" }, { id: "appointments", label: "예약 현황", icon: "calendar" }],
  superadmin: [{ id: "users", label: "사용자·권한", icon: "users" }, { id: "stats", label: "시스템 현황", icon: "chart" }, { id: "breakglass", label: "임상 열람", icon: "key" }, { id: "audit", label: "감사 로그", icon: "audit" }],
  admin: [{ id: "chat", label: "상담", icon: "chat" }, { id: "appointments", label: "예약 관리", icon: "calendar" }, { id: "patients", label: "환자(인적사항)", icon: "patients" }, { id: "audit", label: "감사 로그", icon: "audit" }],
};

const STORE = "medirail.session";

function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function saveSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(STORE, JSON.stringify(s));
    else sessionStorage.removeItem(STORE);
  } catch {
    /* 저장이 막힌 환경에서도 앱은 동작해야 한다 */
  }
}

export default function App() {
  const [session, setSession] = useState<Session | null>(() => {
    const s = loadSession();
    setToken(s?.token ?? null);
    return s;
  });
  const [tab, setTab] = useState<TabId>(() => (session ? TABS[session.role][0].id : "chat"));
  const [patients, setPatients] = useState<PatientLite[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [prefill, setPrefill] = useState("");
  const [expired, setExpired] = useState(false);
  const authRoute = useAuthRoute();

  const logout = useCallback(() => {
    setToken(null);
    saveSession(null);
    setSession(null);
    setTab("chat");
    setSelected(null);
    setPatients([]);
    navigate("/login", true);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setExpired(true);
      logout();
    });
  }, [logout]);

  function onLogin(s: Session) {
    setToken(s.token);
    saveSession(s);
    setExpired(false);
    setSession(s);
    setTab(TABS[s.role][0].id);
    navigate("/", true);   // 로그인·가입 화면 주소에서 벗어난다
  }

  useEffect(() => {
    if (!session || session.role === "patient" || session.role === "superadmin") return;
    api.patients().then(setPatients).catch(() => setPatients([]));
  }, [session]);

  const askAbout = useCallback((patientId: number | null, prompt: string) => {
    if (patientId) setSelected(patientId);
    setPrefill(prompt);
    setTab("chat");
  }, []);
  const clearPrefill = useCallback(() => setPrefill(""), []);

  if (!session) {
    return (
      <div className="shell">
        <a className="skip" href="#main">본문으로 건너뛰기</a>
        {expired && <div className="note warn" role="alert">세션이 만료되었습니다. 다시 로그인해 주세요.</div>}
        {authRoute === "/signup" ? <Signup onLogin={onLogin} /> : authRoute === "/demo" ? <Demo onLogin={onLogin} /> : <Login onLogin={onLogin} />}
      </div>
    );
  }

  const tabs = TABS[session.role];

  return (
    <div className="shell">
      <a className="skip" href="#main">본문으로 건너뛰기</a>
      <header className="browser">
        <TrafficLights />
        <span className="brand"><Sparkle /><span>Medi<b>Rail</b></span></span>
        <span className="addr">medirail · 근거 기반 의료 AI 에이전트 (포트폴리오 · 합성 데이터)</span>
        <span className="who">
          <span className="chip"><Icon name={ROLE_ICON[session.role]} /> {ROLE_LABEL[session.role]}</span>
          {session.readOnly && <span className="chip draft">읽기 전용</span>}
          <span>{session.name}</span>
          <button className="logout" type="button" onClick={logout}>로그아웃</button>
        </span>
      </header>

      <div className="layout">
        <nav aria-label="메뉴" className="win">
          <ul className="notepad">
            {tabs.map((t) => (
              <li key={t.id}>
                <button type="button" aria-current={tab === t.id ? "page" : undefined} onClick={() => setTab(t.id)}>
                  <span className="tab-label"><Icon name={t.icon} />{t.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main id="main" tabIndex={-1}>
          {/* 상담은 탭을 옮겨도 대화가 유지되도록 항상 마운트해 둔다 */}
          {session.role !== "superadmin" && (
            <div hidden={tab !== "chat"}>
              <Chat session={session} patients={patients} selectedPatient={selected} onSelectPatient={setSelected} prefill={prefill} onPrefillUsed={clearPrefill} />
            </div>
          )}
          {tab === "users" && <AdminUsers session={session} />}
          {tab === "stats" && <AdminStatsView />}
          {tab === "breakglass" && <BreakGlass session={session} />}
          {tab === "appointments" && <Appointments session={session} patients={patients} />}
          {tab === "patients" && (
            <Patients session={session} patients={patients} selected={selected} onSelect={setSelected}
              onAsk={(pid, prompt) => askAbout(pid, prompt)} />
          )}
          {tab === "soap" && <Soap onAsk={(p) => askAbout(selected, p)} />}
          {tab === "audit" && <Audit />}
        </main>
      </div>

      <footer className="footer">
        MediRail은 진단·처방을 하지 않는 포트폴리오입니다. 모든 데이터는 합성 데이터입니다. <b>최종 판단은 반드시 의사와 상담하세요.</b>
      </footer>
    </div>
  );
}

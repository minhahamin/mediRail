import { useId, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { navigate } from "../router";
import type { Role, Session } from "../types";
import { Icon } from "./Icon";
import { ErrorNote, Heart, Pin, ROLE_ICON, Sparkle, Tape, Window } from "./ui";

/* ---------- 공통 셸 ---------- */
function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="login" id="main">
      <div className="hero">
        <Sparkle />
        <h1>
          Medi<b>Rail</b>
        </h1>
        <p>근거 기반 · 권한 분리 · 의사 승인 원칙의 의료 AI 에이전트</p>
      </div>
      {children}
      <p className="demo-note">
        포트폴리오 데모입니다. 모든 환자·진료 데이터는 <b>합성 데이터</b>이며, 진단·처방은 하지 않습니다. 최종 판단은 반드시 의사와 상담하세요.
      </p>
    </main>
  );
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: (id: string, describedBy: string | undefined) => ReactNode }) {
  const id = useId();
  const desc = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className="lbl">
      <label htmlFor={id}>{label}</label>
      {children(id, desc)}
      {error ? (
        <span id={`${id}-err`} className="field-error" role="alert">{error}</span>
      ) : hint ? (
        <span id={`${id}-hint`} className="hint">{hint}</span>
      ) : null}
    </div>
  );
}

/* ---------- 로그인 ---------- */
const DEMOS: { username: string; role: Role; name: string; desc: string }[] = [
  { username: "patient1", role: "patient", name: "김하늘", desc: "내 예약 관리, 증상 문진, 약물 안전 정보" },
  { username: "nurse1", role: "nurse", name: "송하린", desc: "문진 요약, 예약 현황, 문헌·약물 조회" },
  { username: "doctor1", role: "doctor", name: "강서준", desc: "문진 요약, SOAP 초안·승인, 문헌·약물 조회" },
  { username: "admin1", role: "admin", name: "임도현", desc: "예약 대행, 감사 로그 (임상 정보 접근 불가)" },
];
const ROLE_NAME: Record<Role, string> = { patient: "환자", nurse: "간호사", doctor: "의사", admin: "원무" };

export function Login({ onLogin }: { onLogin: (s: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(u: string, p: string) {
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(u, p));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "로그인에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(username.trim(), password);
  }

  return (
    <AuthShell>
      <Window title={<><Icon name="key" /> 로그인</>} className="auth-card">
        <form className="stack" onSubmit={onSubmit} noValidate>
          <Field label="아이디">
            {(id) => <input id={id} className="field" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" required />}
          </Field>
          <Field label="비밀번호">
            {(id) => <input id={id} className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />}
          </Field>
          {error && <ErrorNote>{error}</ErrorNote>}
          <button className="btn" disabled={busy || !username.trim() || !password} type="submit">
            {busy ? "로그인 중…" : "로그인"}
          </button>
          <p className="switch">
            아직 계정이 없나요?{" "}
            <button type="button" className="link" onClick={() => navigate("/signup")}>
              회원가입
            </button>
          </p>
        </form>
      </Window>

      <Window title={<><Icon name="users" /> 데모 계정으로 바로 체험하기</>}>
        <p className="muted" style={{ marginTop: 0 }}>역할마다 보이는 화면과 권한이 다릅니다. 클릭하면 바로 입장합니다. (비밀번호 <code>demo1234</code>)</p>
        <div className="accounts">
          {DEMOS.map((d, i) => (
            <button key={d.username} type="button" className="account" disabled={busy} onClick={() => void submit(d.username, "demo1234")}>
              {i % 2 === 0 ? <Tape /> : <Pin />}
              <span className="role-badge"><Icon name={ROLE_ICON[d.role]} /></span>
              <strong>{ROLE_NAME[d.role]}</strong>
              <small>{d.name} · {d.username}</small>
              <small>{d.desc}</small>
              <span className="go">
                <Heart className="inline" /> 입장하기 →
              </span>
            </button>
          ))}
        </div>
      </Window>
    </AuthShell>
  );
}

/* ---------- 회원가입 ---------- */
const USERNAME_RE = /^[a-z0-9_]{4,20}$/;
const RESERVED = ["doctor", "nurse", "admin", "staff", "root", "system", "medirail", "support"];
const THIS_YEAR = new Date().getFullYear();

interface Form {
  username: string;
  password: string;
  confirm: string;
  name: string;
  birthYear: string;
  sex: "" | "F" | "M";
  allergies: string;
  medications: string;
  consent: boolean;
}

/** 서버(services.register_patient)와 같은 규칙. 서버가 최종 판단하고, 여기서는 빠른 피드백만 준다. */
function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {};
  const u = f.username.trim().toLowerCase();
  if (!USERNAME_RE.test(u)) e.username = "영문 소문자·숫자·밑줄(_) 4~20자";
  else if (RESERVED.some((p) => u.startsWith(p))) e.username = "사용할 수 없는 아이디입니다";
  if (f.password.length < 8 || f.password.length > 72 || !/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) e.password = "8~72자, 영문과 숫자를 모두 포함";
  if (f.confirm !== f.password) e.confirm = "비밀번호가 일치하지 않습니다";
  const n = f.name.trim();
  if (n.length < 1 || n.length > 20) e.name = "1~20자로 입력해 주세요";
  const y = Number(f.birthYear);
  if (!Number.isInteger(y) || y < 1900 || y > THIS_YEAR) e.birthYear = `1900~${THIS_YEAR} 사이의 연도`;
  if (!f.sex) e.sex = "성별을 선택해 주세요";
  if (f.allergies.length > 200) e.allergies = "200자 이하";
  if (f.medications.length > 200) e.medications = "200자 이하";
  if (!f.consent) e.consent = "동의가 필요합니다";
  return e;
}

export function Signup({ onLogin }: { onLogin: (s: Session) => void }) {
  const [f, setF] = useState<Form>({ username: "", password: "", confirm: "", name: "", birthYear: "", sex: "", allergies: "", medications: "", consent: false });
  const [touched, setTouched] = useState(false);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const errors = validate(f);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((p) => ({ ...p, [k]: v }));
  const err = (k: keyof Form) => (touched ? errors[k] : undefined);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    setTouched(true);
    setError("");
    if (Object.keys(errors).length) return;
    setBusy(true);
    try {
      onLogin(await api.register({
        username: f.username.trim().toLowerCase(), password: f.password, name: f.name.trim(), birth_year: Number(f.birthYear),
        sex: f.sex as "F" | "M", allergies: f.allergies.trim(), medications: f.medications.trim(),
      }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "회원가입에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <Window title={<><Icon name="sprout" /> 회원가입 (환자 계정)</>} className="auth-card wide">
        <form className="stack" onSubmit={onSubmit} noValidate>
          <div className="note">
            <b>환자 계정</b>만 만들 수 있습니다. 의사·간호사·원무 화면은 <button type="button" className="link" onClick={() => navigate("/login")}>데모 계정</button>으로 체험하세요.
          </div>

          <div className="form-grid">
            <Field label="아이디" hint="영문 소문자·숫자·밑줄(_) 4~20자" error={err("username")}>
              {(id, d) => <input id={id} className="field" value={f.username} onChange={(e) => set("username", e.target.value)} autoComplete="username" autoCapitalize="none" aria-invalid={!!err("username")} aria-describedby={d} maxLength={20} />}
            </Field>
            <Field label="이름 (닉네임 가능)" hint="실명 대신 닉네임을 권장합니다" error={err("name")}>
              {(id, d) => <input id={id} className="field" value={f.name} onChange={(e) => set("name", e.target.value)} autoComplete="nickname" aria-invalid={!!err("name")} aria-describedby={d} maxLength={20} />}
            </Field>
            <Field label="비밀번호" hint="8자 이상, 영문과 숫자 포함" error={err("password")}>
              {(id, d) => <input id={id} className="field" type={show ? "text" : "password"} value={f.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" aria-invalid={!!err("password")} aria-describedby={d} maxLength={72} />}
            </Field>
            <Field label="비밀번호 확인" error={err("confirm")}>
              {(id, d) => <input id={id} className="field" type={show ? "text" : "password"} value={f.confirm} onChange={(e) => set("confirm", e.target.value)} autoComplete="new-password" aria-invalid={!!err("confirm")} aria-describedby={d} maxLength={72} />}
            </Field>
            <Field label="출생연도" error={err("birthYear")}>
              {(id, d) => <input id={id} className="field" inputMode="numeric" value={f.birthYear} onChange={(e) => set("birthYear", e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="예: 1995" aria-invalid={!!err("birthYear")} aria-describedby={d} />}
            </Field>
            <fieldset className="lbl sexset">
              <legend>성별</legend>
              <div className="row">
                {([["F", "여"], ["M", "남"]] as const).map(([v, label]) => (
                  <label key={v} className="pick">
                    <input type="radio" name="sex" value={v} checked={f.sex === v} onChange={() => set("sex", v)} /> {label}
                  </label>
                ))}
              </div>
              {err("sex") && <span className="field-error" role="alert">{err("sex")}</span>}
            </fieldset>
            <Field label="알레르기 (선택)" hint="예: 페니실린 — 가상의 정보로 충분합니다" error={err("allergies")}>
              {(id, d) => <input id={id} className="field" value={f.allergies} onChange={(e) => set("allergies", e.target.value)} aria-describedby={d} maxLength={200} />}
            </Field>
            <Field label="복용 중인 약 (선택)" hint="예: 암로디핀 5mg" error={err("medications")}>
              {(id, d) => <input id={id} className="field" value={f.medications} onChange={(e) => set("medications", e.target.value)} aria-describedby={d} maxLength={200} />}
            </Field>
          </div>

          <label className="pick"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> 비밀번호 보기</label>

          <div className="note warn consent">
            <label className="pick">
              <input type="checkbox" checked={f.consent} onChange={(e) => set("consent", e.target.checked)} aria-invalid={!!err("consent")} />
              <span>
                이 서비스는 <b>포트폴리오 데모</b>입니다. <b>실제 실명·연락처·병력 등 개인정보와 의료정보를 입력하지 않겠습니다.</b> 입력한 내용은 데모 화면에서 의료진 역할에게 보일 수 있습니다.
              </span>
            </label>
            {err("consent") && <span className="field-error" role="alert">{err("consent")}</span>}
          </div>

          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>{busy ? "가입 중…" : "가입하고 시작하기"}</button>
            <p className="switch" style={{ margin: 0 }}>
              이미 계정이 있나요?{" "}
              <button type="button" className="link" onClick={() => navigate("/login")}>로그인</button>
            </p>
          </div>
        </form>
      </Window>
    </AuthShell>
  );
}

import { useState } from "react";
import { api, ApiError } from "../api";
import type { Role, Session } from "../types";
import { ErrorNote, Heart, Pin, ROLE_ICON, Sparkle, Tape, Window } from "./ui";

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

  return (
    <main className="login" id="main">
      <div className="hero">
        <Sparkle />
        <h1>
          Medi<b>Rail</b>
        </h1>
        <p>근거 기반 · 권한 분리 · 의사 승인 원칙의 의료 AI 에이전트</p>
      </div>

      <Window title={<>🔑 데모 계정으로 시작하기</>} bodyClass="stack">
        <div className="accounts">
          {DEMOS.map((d, i) => (
            <button key={d.username} type="button" className="account" disabled={busy} onClick={() => submit(d.username, "demo1234")}>
              {i % 2 === 0 ? <Tape /> : <Pin />}
              <span className="emoji">{ROLE_ICON[d.role]}</span>
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

      <Window title="직접 로그인">
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit(username, password);
          }}
        >
          <label className="lbl">
            아이디
            <input className="field" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder="doctor1" required />
          </label>
          <label className="lbl">
            비밀번호
            <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" placeholder="demo1234" required />
          </label>
          <button className="btn" disabled={busy} type="submit">
            로그인
          </button>
        </form>
        {error && <ErrorNote>{error}</ErrorNote>}
      </Window>

      <p className="demo-note">
        포트폴리오 데모입니다. 모든 환자·진료 데이터는 <b>합성 데이터</b>이며, 진단·처방은 하지 않습니다. 최종 판단은 반드시 의사와 상담하세요.
      </p>
    </main>
  );
}

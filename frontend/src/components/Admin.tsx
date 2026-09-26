import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import type { AdminStats, AdminUser, BreakGlassResult, Session } from "../types";
import { Icon } from "./Icon";
import { Empty, ErrorNote, Notebook, ROLE_LABEL, Spinner, Window } from "./ui";

const ASSIGNABLE = ["patient", "nurse", "doctor", "admin"] as const;

/* ---------- 사용자·권한 ---------- */
export function AdminUsers({ session }: { session: Session }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [me, setMe] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await api.adminUsers());
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "사용자 목록을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void load();
    api.me().then((u) => setMe(u.id)).catch(() => setMe(null));
  }, [load]);

  const shown = useMemo(
    () => (users ?? []).filter((u) => (!roleFilter || u.role === roleFilter) && (!q || `${u.username} ${u.name}`.toLowerCase().includes(q.toLowerCase()))),
    [users, q, roleFilter],
  );

  async function run(fn: () => Promise<unknown>, ok: string) {
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(ok);
      setConfirming(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요청에 실패했습니다.");
    }
  }

  return (
    <Window title={<><Icon name="users" /> 사용자·권한 관리</>}>
      <div className="note" style={{ marginBottom: 12 }}>
        <Icon name="shield" /> 권한 변경은 <b>즉시 반영</b>되고 감사 로그에 기록됩니다. 최상위 관리자 부여는 API로 불가능하며, 자기 자신·최상위 관리자·데모 계정은 변경할 수 없습니다.
        {session.readOnly && <> <b>읽기 전용 관리자</b>라서 변경 버튼이 비활성화되어 있고, 가입자의 아이디·이름은 가려서 표시됩니다.</>}
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <input className="field" style={{ maxWidth: 260 }} placeholder="아이디·이름 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="사용자 검색" />
        <select className="field" style={{ width: "auto" }} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="역할 필터">
          <option value="">모든 역할</option>
          {[...ASSIGNABLE, "superadmin"].map((r) => (<option key={r} value={r}>{ROLE_LABEL[r]}</option>))}
        </select>
        <span className="muted">{shown.length} / {users?.length ?? 0}명</span>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {notice && <div className="note" role="status">{notice}</div>}
      {!users ? (
        <Spinner />
      ) : shown.length === 0 ? (
        <Empty>조건에 맞는 사용자가 없습니다.</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>아이디</th><th>이름</th><th>역할</th><th>상태</th><th>작업</th></tr>
            </thead>
            <tbody>
              {shown.map((u) => {
                const protectedRow = u.is_demo || u.role === "superadmin" || u.id === me;
                const editable = !session.readOnly && !protectedRow;
                const value = draft[u.id] ?? u.role;
                const changed = value !== u.role;
                return (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.name}</td>
                    <td>
                      {editable ? (
                        <select className="field sm" value={value} onChange={(e) => { setDraft((d) => ({ ...d, [u.id]: e.target.value })); setConfirming(null); }} aria-label={`${u.username} 역할`}>
                          {ASSIGNABLE.map((r) => (<option key={r} value={r} disabled={r === "patient" && u.patient_id === null}>{ROLE_LABEL[r]}</option>))}
                        </select>
                      ) : (
                        <span className="chip">{ROLE_LABEL[u.role]}</span>
                      )}
                    </td>
                    <td>
                      <span className={`chip ${u.disabled ? "warn" : "ok"}`}>{u.disabled ? "중지" : "활성"}</span>{" "}
                      {u.is_demo && <span className="chip draft">데모</span>}{" "}
                      {u.read_only && <span className="chip">읽기 전용</span>}{" "}
                      {u.id === me && <span className="chip">나</span>}
                    </td>
                    <td>
                      {protectedRow ? (
                        <span className="muted">보호됨</span>
                      ) : session.readOnly ? (
                        <span className="muted">변경 불가</span>
                      ) : (
                        <span className="row" style={{ flexWrap: "nowrap" }}>
                          {changed && confirming !== u.id && <button className="btn sm" onClick={() => setConfirming(u.id)}>적용</button>}
                          {changed && confirming === u.id && (
                            <>
                              <button className="btn sm danger" onClick={() => void run(() => api.setRole(u.id, value), `${u.username}: ${ROLE_LABEL[u.role]} → ${ROLE_LABEL[value]} 변경했습니다.`)}>
                                {ROLE_LABEL[value]}로 변경 확인
                              </button>
                              <button className="btn sm ghost" onClick={() => { setConfirming(null); setDraft((d) => { const n = { ...d }; delete n[u.id]; return n; }); }}>취소</button>
                            </>
                          )}
                          {!changed && (u.disabled ? (
                            <button className="btn sm ghost" onClick={() => void run(() => api.enableUser(u.id), `${u.username} 계정을 다시 활성화했습니다.`)}>활성화</button>
                          ) : (
                            <button className="btn sm ghost" onClick={() => void run(() => api.disableUser(u.id), `${u.username} 계정의 사용을 중지했습니다. 발급된 토큰도 즉시 무효화됩니다.`)}>사용 중지</button>
                          ))}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Window>
  );
}

/* ---------- 시스템 현황 ---------- */
export function AdminStatsView() {
  const [s, setS] = useState<AdminStats | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.adminStats().then(setS).catch((e) => setError(e instanceof ApiError ? e.message : "현황을 불러오지 못했습니다."));
  }, []);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!s) return <Spinner />;
  const pct = (a: number, b: number) => Math.min(100, Math.round((a / Math.max(b, 1)) * 100));
  const card = (label: string, value: string | number, sub?: string) => (
    <Notebook className="stat">
      <div className="muted">{label}</div>
      <div className="stat-n">{value}</div>
      {sub && <div className="muted">{sub}</div>}
    </Notebook>
  );
  return (
    <Window title={<><Icon name="chart" /> 시스템 현황</>}>
      <div className="grid2 stats">
        {card("전체 사용자", `${s.users} / ${s.users_capacity}`, `중지된 계정 ${s.disabled_users}`)}
        {card("환자 기록", s.patients)}
        {card("예정된 예약", s.appointments_booked)}
        {card("SOAP", `초안 ${s.soap_draft} · 승인 ${s.soap_approved}`)}
        {card("감사 로그", s.audit_entries, `권한 차단 ${s.security_events}건 · 임상 열람(break-glass) ${s.break_glass_events}건`)}
        {card("모델", s.model)}
      </div>
      <Notebook tape>
        <h3><Icon name="users" /> 역할별 사용자</h3>
        <div className="row">
          {Object.entries(s.users_by_role).map(([r, n]) => (<span key={r} className="chip">{ROLE_LABEL[r] ?? r} {n}</span>))}
        </div>
      </Notebook>
      <Notebook pin>
        <h3><Icon name="shield" /> 오늘 AI 요청 사용량 (비용 상한)</h3>
        <div className="bar" role="progressbar" aria-valuenow={s.ai_requests_today} aria-valuemin={0} aria-valuemax={s.ai_requests_limit}>
          <i style={{ width: `${pct(s.ai_requests_today, s.ai_requests_limit)}%` }} />
        </div>
        <p className="muted">{s.ai_requests_today} / {s.ai_requests_limit}회 (응급 안내는 LLM을 쓰지 않아 집계·제한 대상이 아닙니다)</p>
      </Notebook>
    </Window>
  );
}

/* ---------- break-glass: 사유를 남기고 임상 열람 ---------- */
export function BreakGlass({ session }: { session: Session }) {
  const [patientId, setPatientId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<BreakGlassResult | null>(null);
  const valid = Number(patientId) > 0 && reason.trim().length >= 10 && reason.length <= 300;

  async function open() {
    setBusy(true);
    setError("");
    setData(null);
    try {
      setData(await api.breakGlass(Number(patientId), reason.trim()));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "열람에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Window title={<><Icon name="key" /> 임상 기록 열람 (break-glass)</>}>
        <div className="note warn" style={{ marginBottom: 12 }}>
          <Icon name="lock" /> 시스템 관리자도 임상 기록(문진·진료·SOAP·알레르기)은 <b>기본적으로 볼 수 없습니다</b>. 사유를 적고 열람하면 <b>누가·언제·어떤 환자를·왜</b> 열람했는지 감사 로그에 남습니다. 사유에 환자 개인정보는 쓰지 마세요.
          {session.readOnly && <> 읽기 전용 관리자는 시드(합성) 환자 1~8번만 열람할 수 있습니다.</>}
        </div>
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); if (valid) void open(); }}>
          <div className="lbl">
            <label htmlFor="bg-pid">환자 번호</label>
            <input id="bg-pid" className="field" inputMode="numeric" value={patientId} onChange={(e) => setPatientId(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="예: 2" />
          </div>
          <div className="lbl" style={{ gridColumn: "1 / -1" }}>
            <label htmlFor="bg-reason">열람 사유 (10~300자)</label>
            <textarea id="bg-reason" className="field" rows={3} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="예: 환자 본인 요청에 따른 기록 정정 검토" />
            <span className="hint">{reason.trim().length} / 300</span>
          </div>
          <div>
            <button className="btn" type="submit" disabled={!valid || busy}>{busy ? "열람 중…" : "사유를 남기고 열람"}</button>
          </div>
        </form>
        {error && <ErrorNote>{error}</ErrorNote>}
      </Window>

      {data && (
        <>
          <div className="note" role="status"><Icon name="check" /> {data.notice}</div>
          <Window title={<><Icon name="idcard" /> {data.patient.name} · 기본 정보</>}>
            <dl className="kv">
              <dt>번호</dt><dd>#{data.patient.id}</dd>
              <dt>출생연도</dt><dd>{data.patient.birth_year}년 ({data.patient.sex === "F" ? "여" : "남"})</dd>
              <dt>알레르기</dt><dd>{data.patient.allergies}</dd>
              <dt>복용약</dt><dd>{data.patient.medications}</dd>
            </dl>
          </Window>
          <Notebook pin>
            <h3><Icon name="note" /> 문진 원문</h3>
            {data.intake ? <><p>{data.intake.text}</p><p className="muted">접수: {data.intake.created_at}</p></> : <p className="muted">등록된 문진 기록이 없습니다.</p>}
          </Notebook>
          <Notebook tape>
            <h3><Icon name="stethoscope" /> 진료 기록</h3>
            {data.encounters.length === 0 ? <p className="muted">진료 기록이 없습니다.</p> : data.encounters.map((e) => (
              <div key={e.id} style={{ marginBottom: 10 }}><b>{e.visit_date}</b> · {e.chief_complaint}<p className="muted" style={{ margin: 0 }}>{e.notes}</p></div>
            ))}
          </Notebook>
          {data.soap_notes.map((n) => (
            <Notebook key={n.id}>
              <div className="row"><h3><Icon name="soap" /> SOAP #{n.id}</h3><span className="spacer" /><span className={`chip ${n.status === "draft" ? "draft" : "ok"}`}>{n.status === "draft" ? "초안" : "승인됨"}</span></div>
              <div className="soap-grid">
                <div><h4>S</h4>{n.subjective}</div><div><h4>O</h4>{n.objective}</div>
                <div><h4>A</h4>{n.assessment}</div><div><h4>P</h4>{n.plan}</div>
              </div>
            </Notebook>
          ))}
        </>
      )}
    </div>
  );
}

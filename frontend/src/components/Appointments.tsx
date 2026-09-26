import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Appointment, PatientLite, Session } from "../types";
import { Empty, ErrorNote, Heart, Notebook, Spinner, Window, fmtSlot } from "./ui";

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

export function Appointments({ session, patients }: { session: Session; patients: PatientLite[] }) {
  const [list, setList] = useState<Appointment[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [date, setDate] = useState(today());
  const [slots, setSlots] = useState<string[] | null>(null);
  const [slot, setSlot] = useState("");
  const [reason, setReason] = useState("");
  const [patientId, setPatientId] = useState<number | "">("");
  const [busy, setBusy] = useState(false);

  const canBook = session.role === "patient" || session.role === "admin";
  const canCancel = canBook;

  const load = useCallback(async () => {
    try {
      setList(await api.appointments());
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "예약을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!canBook || !date) return;
    let alive = true;
    setSlots(null);
    setSlot("");
    api
      .slots(date)
      .then((r) => alive && setSlots(r.slots))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "시간을 불러오지 못했습니다."));
    return () => {
      alive = false;
    };
  }, [date, canBook]);

  async function book() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const r = await api.book(slot, reason, session.role === "admin" ? Number(patientId) : undefined);
      setNotice(`예약되었습니다: ${fmtSlot(r.slot)} · ${r.doctor_name}`);
      setReason("");
      setSlot("");
      await load();
      setSlots((await api.slots(date)).slots);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "예약에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: number) {
    setError("");
    setNotice("");
    try {
      await api.cancel(id);
      setNotice("예약을 취소했습니다.");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "취소에 실패했습니다.");
    }
  }

  return (
    <div className="stack">
      <Window title={<>📅 {session.role === "patient" ? "내 예약" : "예약 현황"}</>}>
        {error && <ErrorNote>{error}</ErrorNote>}
        {notice && <div className="note">{notice}</div>}
        {!list ? (
          <Spinner />
        ) : list.length === 0 ? (
          <Empty>예정된 예약이 없습니다.</Empty>
        ) : (
          <div className="appt-list">
            {list.map((a) => (
              <div className="player" key={a.id}>
                <Heart />
                <div className="appt">
                  <span className="when">{fmtSlot(a.slot)}</span>
                  {session.role !== "patient" && <span className="chip">{a.patient_name}</span>}
                  <span className="muted">{a.doctor_name}{a.reason ? ` · ${a.reason}` : ""}</span>
                </div>
                <span className="spacer" />
                {canCancel && (
                  <button className="btn danger sm" onClick={() => void cancel(a.id)}>
                    취소
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {session.role === "patient" && <p className="muted">취소는 진료 하루 전 18:00까지 가능하며, 이후에는 전화로 문의해 주세요.</p>}
      </Window>

      {canBook && (
        <Window title={<>✏️ {session.role === "admin" ? "예약 대행" : "새 예약"}</>}>
          <Notebook tape>
            <div className="row">
              {session.role === "admin" && (
                <label className="lbl">
                  환자
                  <select className="field" value={patientId} onChange={(e) => setPatientId(e.target.value ? Number(e.target.value) : "")}>
                    <option value="">선택</option>
                    {patients.map((p) => (
                      <option key={p.id} value={p.id}>
                        #{p.id} {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="lbl">
                날짜
                <input className="field" type="date" min={today()} value={date} onChange={(e) => setDate(e.target.value)} />
              </label>
              <label className="lbl" style={{ flex: 1, minWidth: 180 }}>
                방문 사유 (선택)
                <input className="field" value={reason} maxLength={100} onChange={(e) => setReason(e.target.value)} placeholder="예: 인후통 재진" />
              </label>
            </div>
            <p className="muted" style={{ marginTop: 10 }}>가능한 시간 (평일 09:00–18:00 · 점심 12:30–13:30 제외 · 토 09:00–13:00 · 일 휴진)</p>
            {!slots ? (
              <Spinner label="시간 확인 중" />
            ) : slots.length === 0 ? (
              <Empty>이 날짜에는 예약 가능한 시간이 없습니다.</Empty>
            ) : (
              <div className="slots" role="group" aria-label="예약 가능 시간">
                {slots.map((s) => (
                  <button key={s} className="slot" type="button" aria-pressed={slot === s} onClick={() => setSlot(s)}>
                    {s.slice(11)}
                  </button>
                ))}
              </div>
            )}
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" disabled={!slot || busy || (session.role === "admin" && !patientId)} onClick={() => void book()}>
                {slot ? `${fmtSlot(slot)} 예약하기` : "시간을 선택하세요"}
              </button>
            </div>
          </Notebook>
        </Window>
      )}
    </div>
  );
}

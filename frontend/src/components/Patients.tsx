import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Encounter, Intake, PatientLite, PatientProfile, Session } from "../types";
import { Icon } from "./Icon";
import { Empty, ErrorNote, Notebook, Spinner, Window } from "./ui";

interface Detail {
  profile: PatientProfile;
  intake: Intake | null | undefined; // undefined: 권한 없음
  encounters: Encounter[] | undefined;
}

export function Patients({ session, patients, selected, onSelect, onAsk }: {
  session: Session;
  patients: PatientLite[];
  selected: number | null;
  onSelect: (id: number) => void;
  onAsk: (patientId: number, prompt: string) => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const clinical = session.role === "nurse" || session.role === "doctor";

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    setDetail(null);
    setError("");
    (async () => {
      try {
        const profile = await api.patient(selected);
        const intake = clinical ? await api.intake(selected) : undefined;
        const encounters = session.role === "doctor" ? await api.encounters(selected) : undefined;
        if (alive) setDetail({ profile, intake, encounters });
      } catch (e) {
        if (alive) setError(e instanceof ApiError ? e.message : "환자 정보를 불러오지 못했습니다.");
      }
    })();
    return () => {
      alive = false;
    };
  }, [selected, clinical, session.role]);

  return (
    <div className="split">
      <Window title={<><Icon name="patients" /> 환자 목록</>}>
        <ul className="plist">
          {patients.map((p) => (
            <li key={p.id}>
              <button type="button" aria-current={selected === p.id} onClick={() => onSelect(p.id)}>
                #{p.id} {p.name} <span className="muted">· {p.birth_year}년생 {p.sex === "F" ? "여" : "남"}</span>
              </button>
            </li>
          ))}
        </ul>
        {session.role === "admin" && <p className="muted" style={{ marginTop: 10 }}>원무는 인적사항만 볼 수 있습니다. 알레르기·복용약·문진은 접근이 차단됩니다.</p>}
      </Window>

      <div className="stack">
        {!selected ? (
          <Window title="환자 상세"><Empty>왼쪽에서 환자를 선택하세요.</Empty></Window>
        ) : error ? (
          <ErrorNote>{error}</ErrorNote>
        ) : !detail ? (
          <Spinner />
        ) : (
          <>
            <Window title={<><Icon name="idcard" /> {detail.profile.name} · 기본 정보</>}>
              <dl className="kv">
                <dt>번호</dt><dd>#{detail.profile.id}</dd>
                <dt>출생연도</dt><dd>{detail.profile.birth_year}년 ({detail.profile.sex === "F" ? "여" : "남"})</dd>
                {detail.profile.allergies !== undefined ? (
                  <>
                    <dt>알레르기</dt><dd>{detail.profile.allergies}</dd>
                    <dt>복용약</dt><dd>{detail.profile.medications}</dd>
                  </>
                ) : (
                  <>
                    <dt>임상 정보</dt><dd><span className="chip warn"><Icon name="lock" /> 이 역할은 접근할 수 없습니다</span></dd>
                  </>
                )}
              </dl>
              {clinical && (
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn sm" onClick={() => onAsk(detail.profile.id, "이 환자 문진 요약해줘")}>문진 요약 요청</button>
                  {session.role === "doctor" && (
                    <button className="btn sm ghost" onClick={() => onAsk(detail.profile.id, "이 환자 SOAP 초안 만들어서 저장해줘")}>SOAP 초안 요청</button>
                  )}
                </div>
              )}
            </Window>

            {clinical && (
              <Notebook pin>
                <h3><Icon name="note" /> 문진 원문</h3>
                {detail.intake ? (
                  <>
                    <p>{detail.intake.text}</p>
                    <p className="muted">접수: {detail.intake.created_at}</p>
                  </>
                ) : (
                  <p className="muted">등록된 문진 기록이 없습니다.</p>
                )}
              </Notebook>
            )}

            {detail.encounters && (
              <Notebook tape>
                <h3><Icon name="stethoscope" /> 진료 기록</h3>
                {detail.encounters.length === 0 ? (
                  <p className="muted">진료 기록이 없습니다.</p>
                ) : (
                  detail.encounters.map((e) => (
                    <div key={e.id} style={{ marginBottom: 10 }}>
                      <b>{e.visit_date}</b> · {e.chief_complaint}
                      <p className="muted" style={{ margin: 0 }}>{e.notes}</p>
                    </div>
                  ))
                )}
              </Notebook>
            )}
          </>
        )}
      </div>
    </div>
  );
}

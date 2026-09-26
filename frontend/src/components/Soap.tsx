import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { SoapNote } from "../types";
import { Empty, ErrorNote, Notebook, Spinner, Window } from "./ui";

type Filter = "all" | "draft" | "approved";

export function Soap({ onAsk }: { onAsk: (prompt: string) => void }) {
  const [notes, setNotes] = useState<SoapNote[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setNotes(await api.soaps());
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "SOAP 노트를 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function approve(id: number) {
    setBusyId(id);
    try {
      await api.approve(id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "승인에 실패했습니다.");
    } finally {
      setBusyId(null);
    }
  }

  const shown = (notes ?? []).filter((n) => filter === "all" || n.status === filter);
  const drafts = (notes ?? []).filter((n) => n.status === "draft").length;

  return (
    <Window
      title={<>📓 SOAP 노트 {drafts > 0 && <span className="chip draft">초안 {drafts}</span>}</>}
      actions={
        <button className="btn sm ghost" type="button" onClick={() => onAsk("이 환자 SOAP 초안 만들어서 저장해줘")}>
          + 초안 만들기 (상담)
        </button>
      }
    >
      <div className="note" style={{ marginBottom: 12 }}>
        🔐 AI는 <b>초안만</b> 만들 수 있습니다. 승인 도구는 AI에게 존재하지 않고, <b>의사가 이 화면에서만</b> 승인할 수 있습니다 (human-in-the-loop).
      </div>
      <div className="row" style={{ marginBottom: 12 }} role="group" aria-label="상태 필터">
        {(["all", "draft", "approved"] as Filter[]).map((f) => (
          <button key={f} className={`btn sm ${filter === f ? "" : "ghost"}`} onClick={() => setFilter(f)} aria-pressed={filter === f}>
            {{ all: "전체", draft: "초안", approved: "승인됨" }[f]}
          </button>
        ))}
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!notes ? (
        <Spinner />
      ) : shown.length === 0 ? (
        <Empty>표시할 SOAP 노트가 없습니다. 상담 탭에서 “이 환자 SOAP 초안 만들어서 저장해줘”를 요청해 보세요.</Empty>
      ) : (
        <div className="stack">
          {shown.map((n) => (
            <Notebook key={n.id}>
              <div className="row">
                <h3>{n.patient_name}</h3>
                <span className="muted">{n.visit_date} · {n.chief_complaint}</span>
                <span className="spacer" />
                <span className={`chip ${n.status === "draft" ? "draft" : "ok"}`}>{n.status === "draft" ? "초안 (미승인)" : "✔ 승인됨"}</span>
              </div>
              <div className="soap-grid">
                <div><h4>S · 주관적</h4>{n.subjective}</div>
                <div><h4>O · 객관적</h4>{n.objective}</div>
                <div><h4>A · 평가 (의심 소견)</h4>{n.assessment}</div>
                <div><h4>P · 계획</h4>{n.plan}</div>
              </div>
              {n.status === "draft" && (
                <button className="btn" disabled={busyId === n.id} onClick={() => void approve(n.id)}>
                  검토 후 승인
                </button>
              )}
            </Notebook>
          ))}
        </div>
      )}
    </Window>
  );
}

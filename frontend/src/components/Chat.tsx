import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { RichText } from "../render";
import type { ChatMessage, PatientLite, Role, Session } from "../types";
import { Pin, Window } from "./ui";

const SUGGESTIONS: Record<Role, string[]> = {
  patient: ["토요일 오후 3시에 진료 받을 수 있어?", "내 예약 알려줘", "심바스타틴이랑 클래리트로마이신 같이 먹어도 돼?", "가슴이 쥐어짜듯 아파요"],
  nurse: ["이 환자 문진 요약해줘", "와파린과 아스피린 병용 출혈 위험 문헌을 찾아줘", "실데나필과 질산염제 병용 가능한가요?"],
  doctor: ["이 환자 문진 요약해줘", "이 환자 SOAP 초안 만들어서 저장해줘", "졸피뎀 소아나 노인에게 쓸 때 DUR 주의사항 알려줘", "와파린과 아스피린 병용 출혈 위험 문헌을 찾아줘"],
  admin: ["내일 예약 현황 알려줘", "토요일 진료시간이 어떻게 돼?", "1번 환자 알레르기 알려줘"],
};

const EVENT_LABEL: Record<string, { text: string; warn?: boolean }> = {
  self_repair: { text: "🔁 자가 교정 (검증 실패 → 재작성)" },
  disclaimer_added: { text: "면책 문구 자동 추가" },
  uncited: { text: "근거 목록 자동 첨부" },
  invalid_citation: { text: "🛑 출처 검증 실패 → 폐기", warn: true },
  invalid_pmid: { text: "🛑 논문 번호 검증 실패 → 폐기", warn: true },
  forbidden_claim: { text: "🛑 확정 진단·처방 표현 차단", warn: true },
  safety_assurance: { text: "🛑 '안전' 단정 표현 차단", warn: true },
  tool_denied: { text: "🛑 권한 없는 도구 호출 차단", warn: true },
  emergency_short_circuit: { text: "🚨 응급 즉시 안내 (LLM 호출 없음)", warn: true },
  emergency_keyword_staff: { text: "응급 키워드 감지 (의료진 대화)" },
  max_steps_or_empty: { text: "처리 단계 초과", warn: true },
};

const TOOL_LABEL: Record<string, string> = {
  get_clinic_info: "진료 안내",
  get_available_slots: "예약 가능 시간",
  list_appointments: "예약 목록",
  book_appointment: "예약 생성",
  cancel_appointment: "예약 취소",
  submit_intake: "문진 접수",
  get_patient_profile: "환자 정보",
  get_patient_intake: "문진 조회",
  get_encounter: "진료 기록",
  save_soap_draft: "SOAP 초안 저장",
  search_medical_literature: "PubMed 검색 (MCP)",
  check_drug_interaction: "DUR 병용금기 (MCP)",
  get_drug_safety_info: "DUR 안전정보 (MCP)",
};

interface Props {
  session: Session;
  patients: PatientLite[];
  selectedPatient: number | null;
  onSelectPatient: (id: number | null) => void;
  prefill: string;
  onPrefillUsed: () => void;
}

export function Chat({ session, patients, selectedPatient, onSelectPatient, prefill, onPrefillUsed }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 0,
      role: "assistant",
      text: `안녕하세요, ${session.name}님. MediRail입니다. 진단·처방은 하지 않고, 확인한 근거([D1] 같은 출처)와 함께 안내해 드립니다.\n※ 최종 판단은 반드시 의사와 상담하세요.`,
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const isStaff = session.role !== "patient";

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    endRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "end" });
  }, [messages, busy]);

  useEffect(() => {
    if (prefill) {
      setInput(prefill);
      onPrefillUsed();
    }
  }, [prefill, onPrefillUsed]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    const history = messages
      .filter((m) => m.id !== 0 && !m.error)
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.text }));
    setMessages((m) => [...m, { id: nextId.current++, role: "user", text: message }]);
    setInput("");
    setBusy(true);
    try {
      const { answer, ...meta } = await api.chat(message, history, isStaff ? selectedPatient : null);
      setMessages((m) => [...m, { id: nextId.current++, role: "assistant", text: answer, meta }]);
    } catch (e) {
      const text = e instanceof ApiError ? e.message : "답변을 가져오지 못했습니다.";
      setMessages((m) => [...m, { id: nextId.current++, role: "assistant", text, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  function jumpToSource(msgId: number, srcId: string) {
    const el = document.getElementById(`src-${msgId}-${srcId}`);
    if (!el) return;
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el.classList.add("flash");
    window.setTimeout(() => el.classList.remove("flash"), 1200);
  }

  return (
    <Window title={<>💬 상담 · {isStaff ? "업무 보조" : "AI 안내"}</>} bodyClass="chat">
      <div className="chat-head">
        {isStaff && (
          <label className="row muted">
            선택된 환자
            <select className="field" value={selectedPatient ?? ""} onChange={(e) => onSelectPatient(e.target.value ? Number(e.target.value) : null)}>
              <option value="">(선택 안 함)</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.id} {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="spacer" />
        <span className="safety-bar">🛡️ 응급 감지 · 출처 검증 · 권한 검사가 항상 켜져 있습니다</span>
      </div>

      <div className="thread" role="log" aria-live="polite" aria-label="대화">
        {messages.map((m) => {
          const emergency = !!m.meta?.emergency.length;
          const cls = ["msg", m.role, emergency ? "emergency" : "", m.error ? "error" : ""].join(" ");
          return (
            <div className={cls} key={m.id}>
              <div className="bubble">
                {m.role === "user" ? <p>{m.text}</p> : <RichText text={m.text} onSource={(id) => jumpToSource(m.id, id)} />}
              </div>
              {!!m.meta?.sources.length && (
                <div className="sources" aria-label="출처">
                  {m.meta.sources.map((s) => (
                    <div className="source" id={`src-${m.id}-${s.id}`} key={s.id}>
                      <Pin />
                      <b>[{s.id}]</b> {s.title}
                      {!!s.refs?.length && <span className="refs">{s.refs.map((r) => r.replace(/^PMID:/, "PMID ")).join(" · ")}</span>}
                    </div>
                  ))}
                </div>
              )}
              {m.meta && (m.meta.events.length > 0 || m.meta.tool_calls.length > 0) && (
                <details className="trace">
                  <summary>안전장치·도구 기록</summary>
                  <div className="row">
                    {m.meta.tool_calls.map((t, i) => (
                      <span key={`t${i}`} className={`chip ${t.ok ? "ok" : "warn"}`} title={t.error ?? undefined}>
                        {t.ok ? "🔧" : "⚠️"} {TOOL_LABEL[t.name] ?? t.name}
                      </span>
                    ))}
                    {m.meta.events.map((e, i) => (
                      <span key={`e${i}`} className={`chip ${EVENT_LABEL[e]?.warn ? "warn" : ""}`}>
                        {EVENT_LABEL[e]?.text ?? e}
                      </span>
                    ))}
                    {m.meta.usage.prompt_tokens ? <span className="chip">{m.meta.model} · {(m.meta.usage.prompt_tokens ?? 0) + (m.meta.usage.completion_tokens ?? 0)} tok</span> : null}
                  </div>
                </details>
              )}
            </div>
          );
        })}
        {busy && (
          <div className="msg assistant">
            <div className="bubble">
              <span className="typing" role="status" aria-label="답변 작성 중">
                <i />
                <i />
                <i />
              </span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <div className="suggest">
          {SUGGESTIONS[session.role].map((s) => (
            <button key={s} type="button" disabled={busy} onClick={() => void send(s)}>
              {s}
            </button>
          ))}
        </div>
        <div className="row">
          <textarea
            className="field"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(input);
              }
            }}
            placeholder="메시지를 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
            maxLength={2000}
            aria-label="메시지 입력"
          />
          <button className="btn" type="submit" disabled={busy || !input.trim()}>
            보내기
          </button>
        </div>
      </form>
    </Window>
  );
}

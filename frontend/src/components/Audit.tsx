import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { AuditRow } from "../types";
import { Icon } from "./Icon";
import { Empty, ErrorNote, Spinner, Window } from "./ui";

export function Audit() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState("");

  const load = () =>
    api
      .audit()
      .then((r) => {
        setRows(r);
        setError("");
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "감사 로그를 불러오지 못했습니다."));

  useEffect(() => {
    void load();
  }, []);

  return (
    <Window title={<><Icon name="audit" /> 감사 로그</>} actions={<button className="btn sm ghost" onClick={() => void load()}>새로고침</button>}>
      <p className="muted">
        로그인, 예약, 문진·SOAP 작업, AI 대화(사용한 도구와 안전장치 이벤트)가 기록됩니다. 입력 원문·약물명·검색어는 남기지 않습니다. <span className="chip warn">security.*</span> 행은 AI가 권한 밖의 도구를 호출하려다 차단된 기록입니다.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!rows ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <Empty>기록이 없습니다.</Empty>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>시각</th><th>역할</th><th>동작</th><th>상세</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.action.startsWith("security.") ? "sec" : ""}>
                  <td>{r.ts}</td>
                  <td>{r.role ?? "-"}</td>
                  <td>{r.action}</td>
                  <td className="detail">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Window>
  );
}

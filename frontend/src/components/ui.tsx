import type { ReactNode } from "react";

/** 레퍼런스(세이지 그린 스티커/문구 스타일)의 소품들: 창, 핀, 테이프, 반짝이, 하트 */

export function Pin({ className = "" }: { className?: string }) {
  return (
    <svg className={`pin ${className}`} viewBox="0 0 24 32" aria-hidden="true">
      <path d="M8 2h8l-1 9 4 4v2H5v-2l4-4z" fill="#8fb08c" stroke="#3e6b4a" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 17v13" stroke="#3e6b4a" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Sparkle({ className = "" }: { className?: string }) {
  return (
    <svg className={`sparkle ${className}`} viewBox="0 0 40 40" aria-hidden="true">
      <path d="M20 3c1 9 4 14 17 17-13 3-16 8-17 17-1-9-4-14-17-17 13-3 16-8 17-17z" fill="#f4f5f2" stroke="#3e6b4a" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}

export function Heart({ className = "" }: { className?: string }) {
  return (
    <svg className={`heart ${className}`} viewBox="0 0 40 36" aria-hidden="true">
      <path d="M20 33C6 23 3 14 9 8c4-3 9-2 11 3 2-5 7-6 11-3 6 6 3 15-11 25z" fill="#fff" stroke="#3e6b4a" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}

export function Tape({ className = "" }: { className?: string }) {
  return <span className={`tape ${className}`} aria-hidden="true" />;
}

interface WindowProps {
  title: ReactNode;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
  onClose?: () => void;
  bodyClass?: string;
}

/** 레트로 데스크탑 창: 그린 타이틀바 + X 버튼 */
export function Window({ title, children, className = "", actions, onClose, bodyClass = "" }: WindowProps) {
  return (
    <section className={`win ${className}`}>
      <header className="win-bar">
        <span className="win-title">{title}</span>
        <span className="win-actions">
          {actions}
          {onClose ? (
            <button type="button" className="win-x" onClick={onClose} aria-label="닫기">
              ×
            </button>
          ) : (
            <span className="win-x" aria-hidden="true">×</span>
          )}
        </span>
      </header>
      <div className={`win-body ${bodyClass}`}>{children}</div>
    </section>
  );
}

/** 스파이럴 노트 카드: 상단 링 */
export function Notebook({ children, className = "", tape = false, pin = false }: { children: ReactNode; className?: string; tape?: boolean; pin?: boolean }) {
  return (
    <div className={`notebook ${className}`}>
      {tape && <Tape />}
      {pin && <Pin />}
      {!tape && <div className="rings" aria-hidden="true" />}
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Sparkle />
      <p>{children}</p>
    </div>
  );
}

export function Spinner({ label = "불러오는 중" }: { label?: string }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <Sparkle className="spin" />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="note warn" role="alert">
      {children}
    </div>
  );
}

export const ROLE_LABEL: Record<string, string> = { patient: "환자", doctor: "의사", nurse: "간호사", admin: "원무" };
export const ROLE_ICON: Record<string, string> = { patient: "🌱", doctor: "🩺", nurse: "💚", admin: "🗂️" };

export function fmtSlot(slot: string): string {
  const [d, t] = slot.split(" ");
  const date = new Date(`${d}T00:00:00`);
  const wd = "일월화수목금토"[date.getDay()];
  return `${Number(d.slice(5, 7))}월 ${Number(d.slice(8, 10))}일(${wd}) ${t}`;
}

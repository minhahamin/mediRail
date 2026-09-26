import type { ReactNode } from "react";

/** 화면 전용 SVG 아이콘 세트 (이모지 대신). 24×24 격자, 2px 라운드 스트로크로 스티커 스타일의 아웃라인과 맞춘다. currentColor를 쓰므로 부모 색을 따른다. */
const PATHS = {
  chat: <path d="M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-4.5 3.5V16H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />,
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </>
  ),
  patients: (
    <>
      <rect x="5" y="4.5" width="14" height="16.5" rx="2" />
      <path d="M9 4.5V3.5h6v1M9 11h6M9 15h4" />
    </>
  ),
  soap: (
    <>
      <rect x="5" y="3" width="14" height="18" rx="2" />
      <path d="M9 3v18M12.5 8h3.5M12.5 12h3.5" />
    </>
  ),
  audit: (
    <>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="M15 15l5.5 5.5" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6z" />
      <path d="M8.8 12l2.4 2.4 4.2-4.4" />
    </>
  ),
  wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5L4 16.6 7.4 20l5.3-5.3a4 4 0 0 0 5-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />,
  repeat: <path d="M4.5 11a7.5 7.5 0 0 1 13-4.5L19.5 9M19.5 4.5V9H15M19.5 13a7.5 7.5 0 0 1-13 4.5L4.5 15M4.5 19.5V15H9" />,
  ban: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6 6l12 12" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5l9.5 16.5h-19z" />
      <path d="M12 10v4.5M12 17.5h.01" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="11" width="14" height="9.5" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="15" r="4" />
      <path d="M11 12l9.5-9.5M16.5 6.5l3 3M14 9l2 2" />
    </>
  ),
  sprout: (
    <>
      <path d="M12 21v-9" />
      <path d="M12 12c0-3.8-2.8-6-7-6 0 3.8 2.8 6 7 6z" />
      <path d="M12 14.5c0-3 2.4-5 6.5-5 0 3-2.4 5-6.5 5z" />
    </>
  ),
  stethoscope: (
    <>
      <path d="M6 3.5v6a4 4 0 0 0 8 0v-6M6 3.5H4.5M14 3.5h1.5M10 13.5V15a5 5 0 0 0 10 0v-2" />
      <circle cx="20" cy="11" r="2" />
    </>
  ),
  heart: <path d="M12 20.5C5 15.7 3 12 3 8.7a4.6 4.6 0 0 1 9-1.2 4.6 4.6 0 0 1 9 1.2c0 3.3-2 7-9 11.8z" />,
  folder: <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 9.7v8.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z" />,
  idcard: (
    <>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <circle cx="8.5" cy="11" r="2" />
      <path d="M5.5 16c.6-1.5 1.7-2.2 3-2.2s2.4.7 3 2.2M14 10h4.5M14 14h3" />
    </>
  ),
  note: (
    <>
      <path d="M6.5 3h8l4 4v14h-12z" />
      <path d="M14.5 3v4h4M9.5 12h6M9.5 16h4" />
    </>
  ),
  pencil: (
    <>
      <path d="M4 20l1-4.2L16.2 4.6a1.6 1.6 0 0 1 2.3 0l.9.9a1.6 1.6 0 0 1 0 2.3L8.2 19z" />
      <path d="M14.5 6.3l3.2 3.2" />
    </>
  ),
  chart: (
    <>
      <path d="M5 20V11M11 20V5M17 20v-7" />
      <path d="M2.5 20.5h19" />
    </>
  ),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  users: (
    <>
      <circle cx="9" cy="8.5" r="3.2" />
      <path d="M3 20c.4-3.4 2.9-5.2 6-5.2s5.6 1.8 6 5.2" />
      <path d="M16 5.5a3 3 0 0 1 0 6M17.5 14.8c2 .5 3.2 2.2 3.5 5.2" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return (
    <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}

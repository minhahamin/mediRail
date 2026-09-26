import type { ReactNode } from "react";

/** 답변 텍스트를 가볍게 렌더링한다: 문단, 글머리 기호, **굵게**, [D#] 출처 칩, PMID 링크. (외부 라이브러리 없이, HTML을 직접 삽입하지 않는다) */

const INLINE = /(\*\*[^*]+\*\*|\[D\d+\]|PMID\s*:?\s*\d{5,9})/g;

function inline(text: string, onSource: (id: string) => void, key: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    const src = part.match(/^\[(D\d+)\]$/);
    if (src) {
      return (
        <button key={k} type="button" className="cite" onClick={() => onSource(src[1])} title={`출처 ${src[1]} 보기`}>
          {src[1]}
        </button>
      );
    }
    const pmid = part.match(/^PMID\s*:?\s*(\d{5,9})$/);
    if (pmid) {
      return (
        <a key={k} className="pmid" href={`https://pubmed.ncbi.nlm.nih.gov/${pmid[1]}/`} target="_blank" rel="noreferrer noopener">
          PMID {pmid[1]}
        </a>
      );
    }
    return <span key={k}>{part}</span>;
  });
}

export function RichText({ text, onSource }: { text: string; onSource: (id: string) => void }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = (i: number) => {
    if (!list.length) return;
    blocks.push(
      <ul key={`ul-${i}`}>
        {list.map((li, j) => (
          <li key={j}>{inline(li, onSource, `li-${i}-${j}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      return;
    }
    flush(i);
    if (!line.trim()) return;
    if (line.startsWith("※")) blocks.push(<p key={i} className="disclaimer">{line}</p>);
    else blocks.push(<p key={i}>{inline(line, onSource, `p-${i}`)}</p>);
  });
  flush(text.length);
  return <>{blocks}</>;
}

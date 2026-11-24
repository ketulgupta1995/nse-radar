import type { ReactNode } from "react";

/** Inline **bold**. Text goes through React, so any HTML in it is shown as plain text, never run. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

/** A tiny markdown renderer: headings, bullet lists, bold and paragraphs. No library, no raw HTML. */
export default function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let bullets: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (bullets.length) {
      out.push(
        <ul key={out.length}>
          {bullets.map((b, i) => (
            <li key={i}>{inline(b)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
    if (para.length) {
      out.push(<p key={out.length}>{inline(para.join(" "))}</p>);
      para = [];
    }
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    const b = /^[-*•]\s+(.*)$/.exec(line);
    if (h) {
      flush();
      const level = Math.min(h[1].length + 2, 6); // keep them below the page heading
      const Tag = `h${level}` as "h3" | "h4" | "h5" | "h6";
      out.push(<Tag key={out.length}>{inline(h[2])}</Tag>);
    } else if (b) {
      if (para.length) flush();
      bullets.push(b[1]);
    } else if (line === "") {
      flush();
    } else {
      if (bullets.length) flush();
      para.push(line);
    }
  }
  flush();
  return <div className="markdown">{out}</div>;
}

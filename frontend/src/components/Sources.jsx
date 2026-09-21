import { useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

export default function Sources({ citations, grounded, degraded, note }) {
  const [open, setOpen] = useState(false);
  if (!citations?.length) {
    return note ? (
      <div className="sources">
        <span className="pill" data-tone="degraded">
          {note}
        </span>
      </div>
    ) : null;
  }

  return (
    <div className="sources">
      <button className="sources__toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <BookOpen size={14} />
        {grounded
          ? `${citations.length} transcript ${citations.length === 1 ? "passage" : "passages"}`
          : "Closest passages (below the grounding threshold)"}
      </button>

      {degraded && (
        <p className="source__flag" style={{ marginTop: 8 }}>
          Retrieved with the fallback embedder — ranking is weaker than usual.
        </p>
      )}

      {open && (
        <ul className="sources__list">
          {citations.map((c) => (
            <li key={`${c.chunk_id || c.index}`} className="source" id={`cite-${c.index}`}>
              <div className="source__head">
                <span className="source__index">S{c.index}</span>
                <span className="source__title">{c.title}</span>
                <span className="source__meta">
                  {c.guest ? `${c.guest} · ` : ""}
                  {c.timestamp ? `${c.timestamp} · ` : ""}
                  {c.score?.toFixed(2)}
                </span>
              </div>
              <p className="source__quote">“{c.quote}”</p>
              {c.synthetic && (
                <span className="source__flag">Synthetic sample transcript, not a real episode</span>
              )}
              {c.url && !c.synthetic && (
                <a
                  className="sources__toggle"
                  style={{ marginTop: 6 }}
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink size={12} /> Open episode
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

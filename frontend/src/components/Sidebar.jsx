import { Database, Plus, Trash2, X } from "lucide-react";

import ModelMenu from "./ModelMenu.jsx";
import { relativeTime } from "../lib/format.js";

const CURRENT_TRANSCRIPT_COUNT = 10;

export default function Sidebar({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onClose,
  config,
  onConfigChange,
  knowledge,
}) {
  return (
    <nav className="rail" aria-label="Chats">
      <div className="rail__brand">
        <h1>Lenny Growth Assistant</h1>
        <span>v1.0</span>
        <button className="iconbtn rail__close" onClick={onClose} aria-label="Close menu">
          <X size={14} />
        </button>
      </div>

      <button className="rail__new" onClick={onCreate}>
        <Plus size={15} /> New chat
      </button>

      <p className="rail__section">
        {sessions.length ? "Recent" : "No chats yet"}
      </p>

      <ul className="rail__list">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className="rail__item"
              aria-current={s.id === activeId}
              onClick={() => onSelect(s.id)}
            >
              <span className="rail__title">{s.title}</span>
              <span className="rail__meta">
                {relativeTime(s.updated_at)}
                {s.message_count ? ` · ${s.message_count} messages` : ""}
              </span>
              <span
                className="rail__delete"
                role="button"
                tabIndex={0}
                aria-label={`Delete ${s.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.stopPropagation();
                    e.preventDefault();
                    onDelete(s.id);
                  }
                }}
              >
                <Trash2 size={13} />
              </span>
            </button>
          </li>
        ))}
      </ul>

      <div className="rail__foot">
        {knowledge && (
          <span className="pill" title={`Embedded with ${knowledge.embedding_model || "unknown"}`}>
            <Database size={11} />
            {CURRENT_TRANSCRIPT_COUNT} transcripts · {knowledge.total_chunks} chunks
          </span>
        )}
        {knowledge?.synthetic_present && (
          <span className="pill" data-tone="degraded">
            Sample corpus loaded — replace before a real evaluation
          </span>
        )}
        <ModelMenu config={config} onChange={onConfigChange} />
      </div>
    </nav>
  );
}

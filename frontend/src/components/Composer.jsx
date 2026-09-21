import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

const MODES = [
  { id: null, label: "Auto" },
  { id: "grounded_answer", label: "Answer" },
  { id: "ship30_essay", label: "Ship 30 essay" },
  { id: "artifact:markdown", label: "Markdown doc" },
  { id: "artifact:html", label: "HTML artifact" },
];

export default function Composer({ onSend, onStop, busy, disabled }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState(null);
  const area = useRef(null);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  function submit() {
    const value = text.trim();
    if (!value || busy || disabled) return;
    const [skill, kind] = (mode || "").split(":");
    onSend(value, { skill: skill || null, artifactKind: kind || null });
    setText("");
  }

  return (
    <div className="composer">
      <div className="composer__inner">
        <div className="composer__modes" role="group" aria-label="Response type">
          {MODES.map((m) => (
            <button
              key={m.label}
              className="mode"
              aria-pressed={mode === m.id}
              onClick={() => setMode(m.id)}
              type="button"
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="composer__field">
          <label className="visually-hidden" htmlFor="composer-input">
            Ask about product and growth
          </label>
          <textarea
            id="composer-input"
            ref={area}
            rows={1}
            value={text}
            disabled={disabled}
            placeholder={
              disabled ? "Start a new chat to begin" : "Ask about pricing, retention, loops, onboarding…"
            }
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          {busy ? (
            <button className="composer__send" onClick={onStop} aria-label="Stop generating">
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button
              className="composer__send"
              onClick={submit}
              disabled={!text.trim() || disabled}
              aria-label="Send message"
            >
              <ArrowUp size={16} />
            </button>
          )}
        </div>

        <p className="composer__hint">
          <span>Enter sends · Shift+Enter for a new line</span>
          <span>Answers cite the transcript passages they came from</span>
        </p>
      </div>
    </div>
  );
}

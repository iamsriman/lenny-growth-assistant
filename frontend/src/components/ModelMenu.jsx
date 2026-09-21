import { useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";

import { api } from "../lib/api.js";

const DESCRIPTIONS = {
  ollama: "Runs on this machine. No data leaves the laptop.",
  anthropic: "Claude via the Anthropic API. Needs ANTHROPIC_API_KEY.",
  openai: "GPT via the OpenAI API. Needs OPENAI_API_KEY.",
  groq: "Llama via the Groq API. Needs GROQ_API_KEY.",
};

const DEFAULT_PROVIDERS = ["ollama", "anthropic", "openai", "groq"];
const DEFAULT_MODELS = {
  groq: "openai/gpt-oss-120b",
};

export default function ModelMenu({ config, onChange }) {
  const [open, setOpen] = useState(false);
  const [statuses, setStatuses] = useState([]);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function away(event) {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false);
    }
    function esc(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    api.providers().then((r) => setStatuses(r.providers || [])).catch(() => setStatuses([]));
  }, [open]);

  const active = config?.active?.provider;
  const activeStatus = statuses.find((s) => s.name === active);
  const dotState = !statuses.length ? "unknown" : activeStatus?.available ? "up" : "down";
  const providers = [...new Set([...(config?.providers || []), ...DEFAULT_PROVIDERS])];

  async function pick(name) {
    if (name === active) return setOpen(false);
    setBusy(true);
    try {
      const next = await api.setConfig({ provider: name });
      onChange(next);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="model" ref={ref}>
      <button
        className="model__trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={busy}
      >
        <span className="model__dot" data-state={dotState} />
        <span className="model__label">
          <b>{active || "—"}</b>
          <span>{config?.active?.model || "loading"}</span>
        </span>
        <ChevronUp size={14} />
      </button>

      {open && (
        <div className="model__panel" role="menu">
          {providers.map((name) => {
            const status = statuses.find((s) => s.name === name);
            const ready = status?.available;
            return (
              <button
                key={name}
                role="menuitemradio"
                aria-checked={name === active}
                className="model__option"
                onClick={() => pick(name)}
                disabled={busy}
              >
                <span className="model__dot" data-state={!status ? "unknown" : ready ? "up" : "down"} />
                <span>
                  <b>
                    {name} {name === active && "·"}
                  </b>
                  <small>{config?.models?.[name] || DEFAULT_MODELS[name] || "model not configured"}</small>
                  <small>{status?.detail || DESCRIPTIONS[name]}</small>
                </span>
              </button>
            );
          })}
          <p className="model__note">
            Switching applies to the next message. Embeddings stay on{" "}
            <b>{config?.embedding_provider}</b> — Anthropic has no embeddings API, so the
            index is never re-embedded by a model change.
            {config?.fallback_provider && (
              <>
                {" "}
                Fallback if the active provider fails: <b>{config.fallback_provider}</b>.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

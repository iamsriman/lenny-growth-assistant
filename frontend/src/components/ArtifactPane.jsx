import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import { Check, Code2, Copy, Download, Eye, Shield, X } from "lucide-react";

import Markdown from "./Markdown.jsx";
import { api } from "../lib/api.js";

/**
 * The artifact viewer.
 *
 * Isolation, in the order an attacker would meet it:
 *   1. The backend sanitises the model's output and injects a CSP meta tag.
 *   2. DOMPurify runs again here, so a compromised or bypassed backend still
 *      cannot hand raw markup to this document.
 *   3. The result is rendered into an <iframe srcdoc> whose sandbox never
 *      includes `allow-same-origin`. The frame is therefore an opaque origin:
 *      artifact script cannot read our DOM, cookies, localStorage, or call our
 *      API — even with a perfect sanitiser bypass.
 *
 * Only step 3 is load-bearing. Steps 1 and 2 catch accidents early and make
 * the failure visible in the Security tab instead of silent.
 */
const SANDBOX_WITH_SCRIPTS = "allow-scripts allow-popups allow-modals";
const SANDBOX_STATIC = "allow-popups";

export default function ArtifactPane({ artifact, onClose }) {
  const [tab, setTab] = useState("preview");
  const [scriptsOn, setScriptsOn] = useState(false);
  const [copied, setCopied] = useState(false);
  const [policy, setPolicy] = useState(null);

  useEffect(() => {
    setTab("preview");
    setScriptsOn(false);
  }, [artifact?.id]);

  useEffect(() => {
    api.artifactPolicy().then(setPolicy).catch(() => setPolicy(null));
  }, []);

  const purified = useMemo(() => {
    if (!artifact || artifact.kind !== "html") return "";
    return DOMPurify.sanitize(artifact.content, {
      WHOLE_DOCUMENT: true,
      ADD_TAGS: ["style", "meta", "svg", "path", "circle", "rect", "line", "polyline", "polygon", "g", "text"],
      ADD_ATTR: ["viewBox", "http-equiv", "content", "charset"],
      FORBID_TAGS: ["iframe", "object", "embed", "base", "form", "link"],
      FORBID_ATTR: ["onerror", "onload", "onclick", "formaction"],
      ALLOW_DATA_ATTR: true,
      // Keep <script> only when the viewer has explicitly opted in; the
      // sandbox is what makes that safe, not this flag.
      ...(scriptsOn ? { ADD_TAGS: ["script", "style", "meta", "svg", "path", "circle", "rect", "line", "polyline", "polygon", "g", "text"] } : {}),
    });
  }, [artifact, scriptsOn]);

  if (!artifact) return null;

  const scriptsPresent = (artifact.sanitiser_report?.scripts_kept || 0) > 0;
  const removed = artifact.sanitiser_report?.removed || [];

  async function copy() {
    try {
      await navigator.clipboard.writeText(artifact.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <aside className="artifact" aria-label="Artifact viewer">
      <div className="artifact__bar">
        <h3 title={artifact.title}>{artifact.title}</h3>
        <span className="pill">{artifact.kind === "html" ? "HTML" : "Markdown"}</span>
        <button className="iconbtn" onClick={copy} aria-label="Copy artifact source">
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy"}
        </button>
        <a className="iconbtn" href={api.artifactDownloadUrl(artifact.id)} download>
          <Download size={14} /> Save
        </a>
        <button className="iconbtn" onClick={onClose} aria-label="Close artifact viewer">
          <X size={14} />
        </button>
      </div>

      <div className="artifact__tabs" role="tablist">
        <button className="tab" role="tab" aria-selected={tab === "preview"} onClick={() => setTab("preview")}>
          <Eye size={12} style={{ verticalAlign: -2, marginRight: 5 }} />
          Preview
        </button>
        <button className="tab" role="tab" aria-selected={tab === "source"} onClick={() => setTab("source")}>
          <Code2 size={12} style={{ verticalAlign: -2, marginRight: 5 }} />
          Source
        </button>
        <button className="tab" role="tab" aria-selected={tab === "security"} onClick={() => setTab("security")}>
          <Shield size={12} style={{ verticalAlign: -2, marginRight: 5 }} />
          Security
          {removed.length > 0 && " ·"}
        </button>
        {artifact.kind === "html" && scriptsPresent && tab === "preview" && (
          <button
            className="iconbtn"
            style={{ marginLeft: "auto", marginBottom: 6 }}
            aria-pressed={scriptsOn}
            onClick={() => setScriptsOn((v) => !v)}
          >
            {scriptsOn ? "Scripts running" : "Run scripts"}
          </button>
        )}
      </div>

      <div className="artifact__body">
        {tab === "preview" &&
          (artifact.kind === "html" ? (
            <iframe
              key={`${artifact.id}-${scriptsOn}`}
              className="artifact__frame"
              title={artifact.title}
              sandbox={scriptsOn ? SANDBOX_WITH_SCRIPTS : SANDBOX_STATIC}
              referrerPolicy="no-referrer"
              srcDoc={purified}
            />
          ) : (
            <div className="artifact__doc">
              <Markdown>{artifact.content}</Markdown>
            </div>
          ))}

        {tab === "source" && <pre className="artifact__code">{artifact.content}</pre>}

        {tab === "security" && (
          <div className="security">
            <p>
              This document came from a language model, so the viewer treats it as untrusted.
              It renders inside a cross-origin sandboxed frame: script inside it cannot read
              this page, your session, or anything stored in the browser.
            </p>

            <h4>What the sanitiser changed</h4>
            {removed.length ? (
              <ul>
                {removed.map((item) => (
                  <li key={item}>Removed: {item}</li>
                ))}
              </ul>
            ) : (
              <p style={{ color: "var(--ink-faint)" }}>Nothing. The output was already clean.</p>
            )}
            {artifact.kind === "html" && (
              <p style={{ color: "var(--ink-faint)" }}>
                Inline scripts kept: {artifact.sanitiser_report?.scripts_kept ?? 0}
                {scriptsPresent && !scriptsOn && " — not running until you choose Run scripts."}
              </p>
            )}

            <h4>Sandbox in use</h4>
            <p>
              <code>sandbox="{scriptsOn ? SANDBOX_WITH_SCRIPTS : SANDBOX_STATIC}"</code>
              {" — "}
              <code>allow-same-origin</code> is never granted.
            </p>

            {policy && (
              <>
                <h4>Blocked inside artifacts</h4>
                <ul>
                  {policy.blocked.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <h4>Content-Security-Policy applied to the document</h4>
                <p>
                  <code>{policy.csp}</code>
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

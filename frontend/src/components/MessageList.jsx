import { Fragment } from "react";
import { AlertTriangle, FileText, Sparkles } from "lucide-react";

import Markdown from "./Markdown.jsx";
import Sources from "./Sources.jsx";
import { skillLabel, stageLabel } from "../lib/format.js";

const PROMPTS = [
  {
    title: "What actually predicts retention?",
    sub: "Grounded answer with transcript citations",
    text: "What does the corpus say actually predicts week-four retention, and how do teams find it?",
  },
  {
    title: "Write a Ship 30 essay on pricing",
    sub: "~1,250 words, checked against the Ship 30 rules",
    text: "Write a Ship 30 for 30 essay about choosing a value metric for product-led pricing.",
  },
  {
    title: "Build an HTML one-pager",
    sub: "Renders beside the chat in the artifact viewer",
    text: "Build an HTML one-pager summarising how growth loops decay and what to do about it.",
  },
  {
    title: "Compare funnels and loops",
    sub: "Follow-ups keep the session's context",
    text: "Compare funnels and growth loops as planning models. Which one should a growth team organise around?",
  },
];

function Trace({ message }) {
  const route = message.meta?.route;
  const critique = message.meta?.critique;
  if (!route && !message.provider) return null;
  return (
    <div className="trace">
      {message.skill && (
        <span className="pill">
          {message.skill === "ship30_essay" ? <Sparkles size={11} /> : null}
          {skillLabel(message.skill)}
        </span>
      )}
      <span className="pill" data-tone={message.grounded ? "grounded" : "degraded"}>
        {message.grounded ? "Grounded in transcripts" : "Not supported by the corpus"}
      </span>
      {message.provider && (
        <span className="pill">
          {message.provider}
          {message.model ? ` · ${message.model}` : ""}
        </span>
      )}
      {typeof message.latency_ms === "number" && (
        <span className="pill">{(message.latency_ms / 1000).toFixed(1)}s</span>
      )}
      {critique && (
        <span className="pill" data-tone={critique.passed ? "grounded" : "degraded"}>
          {critique.word_count} words · Ship 30 checks {Math.round(critique.score * 100)}%
        </span>
      )}
      {route?.reason && (
        <span title={`Routed by ${route.stage}: ${route.reason}`} className="pill">
          routed by {route.stage}
        </span>
      )}
    </div>
  );
}

function Message({ message, onOpenArtifact }) {
  const isUser = message.role === "user";
  return (
    <article className={`msg msg--${isUser ? "user" : "assistant"}`}>
      {!isUser && <Trace message={message} />}
      <div className="msg__role">{isUser ? "You" : "Assistant"}</div>
      <div className="msg__body">
        {isUser ? message.content : <Markdown>{message.content}</Markdown>}
      </div>

      {!isUser && message.artifact && (
        <button
          className="iconbtn"
          style={{ marginTop: 12 }}
          onClick={() => onOpenArtifact(message.artifact)}
        >
          <FileText size={14} /> Open “{message.artifact.title}”
        </button>
      )}

      {!isUser && (
        <Sources
          citations={message.citations}
          grounded={message.grounded}
          degraded={message.meta?.retrieval?.degraded}
          note={message.meta?.retrieval?.note}
        />
      )}
    </article>
  );
}

export default function MessageList({
  messages,
  streaming,
  stage,
  stageData,
  error,
  onOpenArtifact,
  onPrompt,
}) {
  if (!messages.length && !streaming && !error) {
    return (
      <div className="empty">
        <h3>Ask the podcast archive, not the internet.</h3>
        <p>
          Every answer here is built from Lenny’s Podcast transcripts and shows the passages it
          used. Ask a question, or pick one of these to see how it works.
        </p>
        <div className="empty__grid">
          {PROMPTS.map((p) => (
            <button key={p.title} className="empty__card" onClick={() => onPrompt(p.text)}>
              <b>{p.title}</b>
              <span>{p.sub}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="thread">
      {messages.map((m) => (
        <Fragment key={m.id}>
          <Message message={m} onOpenArtifact={onOpenArtifact} />
        </Fragment>
      ))}

      {streaming && (
        <article className="msg msg--assistant">
          <div className="trace">
            <span className="pill">
              {stage ? stageLabel(stage, stageData) : "Working"}
            </span>
            {stageData?.critique && !stageData.critique.passed && (
              <span className="pill" data-tone="degraded">
                {stageData.critique.failures?.[0]}
              </span>
            )}
          </div>
          <div className="msg__role">Assistant</div>
          <div className="msg__body">
            {streaming.content ? (
              <Markdown>{streaming.content}</Markdown>
            ) : (
              <span className="typing" aria-label="Generating">
                <span />
                <span />
                <span />
              </span>
            )}
          </div>
          {streaming.citations?.length > 0 && (
            <Sources
              citations={streaming.citations}
              grounded={streaming.grounded}
              degraded={streaming.degraded}
              note={streaming.note}
            />
          )}
        </article>
      )}

      {error && (
        <div className="notice" data-tone="error" role="alert">
          <strong>
            <AlertTriangle size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
            {error.message}
          </strong>
          {error.remediation && <div>{error.remediation}</div>}
          {error.requestId && (
            <div style={{ marginTop: 6, fontSize: 12 }}>
              Request id <code>{error.requestId}</code> — search the backend logs for it.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

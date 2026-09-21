import { useCallback, useEffect, useRef, useState } from "react";
import { Menu, PanelRight } from "lucide-react";

import ArtifactPane from "./components/ArtifactPane.jsx";
import Composer from "./components/Composer.jsx";
import MessageList from "./components/MessageList.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { api, ApiError, streamChat } from "./lib/api.js";

const EMPTY_STREAM = { content: "", citations: [], grounded: false, degraded: false, note: "" };

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(null);
  const [stage, setStage] = useState(null);
  const [stageData, setStageData] = useState(null);
  const [error, setError] = useState(null);
  const [artifact, setArtifact] = useState(null);
  const [config, setConfig] = useState(null);
  const [knowledge, setKnowledge] = useState(null);
  const [railOpen, setRailOpen] = useState(false);
  const [booted, setBooted] = useState(false);

  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const pinnedRef = useRef(true);

  // ---- boot ------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const [cfg, list, kb] = await Promise.all([
          api.config(),
          api.listSessions(),
          api.knowledge().catch(() => null),
        ]);
        setConfig(cfg);
        setKnowledge(kb);
        setSessions(list);
        if (list.length) {
          setActiveId(list[0].id);
        } else {
          const created = await api.createSession();
          setSessions([created]);
          setActiveId(created.id);
        }
      } catch (err) {
        setError(toNotice(err));
      } finally {
        setBooted(true);
      }
    })();
  }, []);

  // ---- load a session --------------------------------------------------
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    setMessages([]);
    setArtifact(null);
    setError(null);
    (async () => {
      try {
        const detail = await api.getSession(activeId);
        if (cancelled) return;
        const artifacts = await api.listArtifacts(activeId).catch(() => []);
        const byMessage = new Map();
        for (const a of artifacts) byMessage.set(a.id, a);
        setMessages(
          detail.messages.map((m) => ({
            ...m,
            artifact: artifacts.find((a) => a.title && m.meta?.artifact_id === a.id) || null,
          }))
        );
        // Re-attach artifacts to the assistant message that produced them.
        if (artifacts.length) {
          const full = await Promise.all(artifacts.map((a) => api.getArtifact(a.id)));
          if (cancelled) return;
          setMessages((prev) =>
            prev.map((m) => {
              const match = full.find((a) => a.message_id === m.id);
              return match ? { ...m, artifact: match } : m;
            })
          );
        }
      } catch (err) {
        if (!cancelled) setError(toNotice(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // ---- autoscroll, but only while the reader is at the bottom ----------
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  // ---- actions ---------------------------------------------------------
  async function newChat() {
    try {
      const created = await api.createSession();
      setSessions((prev) => [created, ...prev]);
      setActiveId(created.id);
      setRailOpen(false);
    } catch (err) {
      setError(toNotice(err));
    }
  }

  async function removeChat(id) {
    try {
      await api.deleteSession(id);
      const rest = sessions.filter((s) => s.id !== id);
      setSessions(rest);
      if (id === activeId) {
        if (rest.length) setActiveId(rest[0].id);
        else await newChat();
      }
    } catch (err) {
      setError(toNotice(err));
    }
  }

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(null);
    setStage(null);
  }

  async function send(text, { skill = null, artifactKind = null } = {}) {
    if (!activeId) return;
    setError(null);
    pinnedRef.current = true;

    const optimistic = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setStreaming({ ...EMPTY_STREAM });

    const controller = new AbortController();
    abortRef.current = controller;

    let collected = { ...EMPTY_STREAM };
    let routeInfo = null;
    let artifactPayload = null;

    try {
      await streamChat(
        { session_id: activeId, message: text, skill, artifact_kind: artifactKind },
        (event, data) => {
          if (event === "status") {
            setStage(data.stage);
            setStageData(data);
          } else if (event === "route") {
            routeInfo = data;
          } else if (event === "citations") {
            collected = {
              ...collected,
              citations: data.citations || [],
              grounded: !!data.grounded,
              degraded: !!data.degraded,
              note: data.note || "",
            };
            setStreaming({ ...collected });
          } else if (event === "token") {
            collected = { ...collected, content: collected.content + (data.text || "") };
            setStreaming({ ...collected });
          } else if (event === "artifact") {
            artifactPayload = data;
            setArtifact(data);
          } else if (event === "error") {
            setError({
              message: data.message,
              remediation: data.remediation,
              requestId: data.request_id,
            });
          } else if (event === "done") {
            const assistant = {
              id: data.message_id || `assistant-${Date.now()}`,
              role: "assistant",
              content: collected.content,
              skill: data.skill,
              provider: data.provider,
              model: data.model,
              latency_ms: data.latency_ms,
              grounded: data.grounded,
              citations: collected.citations,
              meta: {
                route: routeInfo,
                retrieval: { degraded: collected.degraded, note: collected.note },
                critique: stageDataCritique(),
              },
              artifact: artifactPayload,
              created_at: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, assistant]);
            setSessions((prev) =>
              prev.map((s) =>
                s.id === activeId
                  ? {
                      ...s,
                      title: data.session_title || s.title,
                      updated_at: new Date().toISOString(),
                      message_count: (s.message_count || 0) + 2,
                    }
                  : s
              )
            );
          }
        },
        controller.signal
      );
    } catch (err) {
      if (err.name !== "AbortError") setError(toNotice(err));
    } finally {
      abortRef.current = null;
      setStreaming(null);
      setStage(null);
      setStageData(null);
    }

    function stageDataCritique() {
      return stageData?.critique || null;
    }
  }

  const activeSession = sessions.find((s) => s.id === activeId);

  return (
    <div className="shell" data-artifact={artifact ? "open" : "closed"} data-rail={railOpen ? "open" : "closed"}>
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={(id) => {
          setActiveId(id);
          setRailOpen(false);
        }}
        onCreate={newChat}
        onDelete={removeChat}
        onClose={() => setRailOpen(false)}
        config={config}
        onConfigChange={setConfig}
        knowledge={knowledge}
      />

      {railOpen && <button className="scrim" aria-label="Close menu" onClick={() => setRailOpen(false)} />}

      <main className="chat">
        <header className="chat__bar">
          <button className="iconbtn chat__menu" onClick={() => setRailOpen(true)} aria-label="Open menu">
            <Menu size={15} />
          </button>
          <h2>{activeSession?.title || (booted ? "New chat" : "Loading…")}</h2>
          {config?.knowledge_base && !config.knowledge_base.ready && (
            <span className="pill" data-tone="error">
              Knowledge base empty — run ingestion
            </span>
          )}
          {artifact && (
            <button className="iconbtn" onClick={() => setArtifact(null)}>
              <PanelRight size={14} /> Hide artifact
            </button>
          )}
        </header>

        <div className="chat__scroll" ref={scrollRef} onScroll={onScroll}>
          <MessageList
            messages={messages}
            streaming={streaming}
            stage={stage}
            stageData={stageData}
            error={error}
            onOpenArtifact={setArtifact}
            onPrompt={(t) => send(t)}
          />
        </div>

        <Composer onSend={send} onStop={stop} busy={!!streaming} disabled={!activeId} />
      </main>

      {artifact && <ArtifactPane artifact={artifact} onClose={() => setArtifact(null)} />}
    </div>
  );
}

function toNotice(err) {
  if (err instanceof ApiError) {
    return { message: err.message, remediation: err.remediation, requestId: err.requestId };
  }
  return { message: err?.message || "Something failed.", remediation: "" };
}

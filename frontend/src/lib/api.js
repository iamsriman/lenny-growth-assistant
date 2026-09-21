// Single place that knows how to talk to the backend. Every failure comes back
// as an ApiError with a message and a remediation, so the UI never has to show
// a bare "something went wrong".

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, { code = "error", remediation = "", requestId = "", status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.remediation = remediation;
    this.requestId = requestId;
    this.status = status;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Can't reach the API.", {
      code: "network",
      remediation: "Check that the backend is running on port 8000.",
    });
  }

  if (response.status === 204) return null;

  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const err = payload?.error || {};
    throw new ApiError(err.message || `Request failed with ${response.status}.`, {
      code: err.code || "http_error",
      remediation: err.remediation || "",
      requestId: err.request_id || response.headers.get("x-request-id") || "",
      status: response.status,
    });
  }
  return payload;
}

export const api = {
  readiness: () => request("/health/ready"),
  config: () => request("/api/config"),
  setConfig: (patch) => request("/api/config", { method: "PATCH", body: patch }),
  providers: () => request("/api/config/providers"),

  listSessions: () => request("/api/sessions"),
  createSession: (payload = {}) => request("/api/sessions", { method: "POST", body: payload }),
  getSession: (id) => request(`/api/sessions/${id}`),
  deleteSession: (id) => request(`/api/sessions/${id}`, { method: "DELETE" }),
  renameSession: (id, title) =>
    request(`/api/sessions/${id}`, { method: "PATCH", body: { title } }),

  getArtifact: (id) => request(`/api/artifacts/${id}`),
  listArtifacts: (sessionId) => request(`/api/artifacts?session_id=${sessionId}`),
  artifactPolicy: () => request("/api/artifacts/meta/policy"),
  artifactDownloadUrl: (id) => `${BASE}/api/artifacts/${id}/download`,

  knowledge: () => request("/api/knowledge/documents"),
};

/**
 * POST /api/chat/stream and dispatch SSE events to `onEvent`.
 *
 * We parse the stream by hand rather than using EventSource because
 * EventSource cannot issue a POST, and the turn needs a JSON body.
 */
export async function streamChat(payload, onEvent, signal) {
  const response = await fetch(`${BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail = {};
    try {
      detail = (await response.json())?.error || {};
    } catch {
      /* body was not json */
    }
    throw new ApiError(detail.message || "The assistant could not start.", {
      code: detail.code || "stream_failed",
      remediation: detail.remediation || "Check the backend logs.",
      requestId: detail.request_id || "",
      status: response.status,
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let event = "message";
      const dataLines = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      try {
        onEvent(event, JSON.parse(dataLines.join("\n")));
      } catch {
        onEvent(event, { raw: dataLines.join("\n") });
      }
    }
  }
}

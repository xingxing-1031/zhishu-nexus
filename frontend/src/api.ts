import type {
  AnalysisOutcome,
  AuditEntry,
  MetricDefinition,
  Overview,
  SessionInfo,
  StreamEvent,
  TraceResponse,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

async function parseError(response: Response): Promise<never> {
  let message = `请求失败（${response.status}）`;
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string") message = payload.detail;
  } catch {
    // Keep the stable fallback when an upstream proxy returns non-JSON.
  }
  throw new ApiError(message, response.status);
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) return parseError(response);
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string }>("/health"),
  ready: () => getJson<{ status: string }>("/ready"),
  session: () => getJson<SessionInfo>("/session"),
  overview: () => getJson<Overview>("/demo/overview"),
  trace: (requestId: string) =>
    getJson<TraceResponse>(`/analysis/${encodeURIComponent(requestId)}/trace`),
  metrics: () => getJson<MetricDefinition[]>("/admin/metrics"),
  audit: (query: string) => getJson<AuditEntry[]>(`/admin/audit?${query}`),
  async login(username: string, password: string): Promise<SessionInfo> {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) return parseError(response);
    return response.json() as Promise<SessionInfo>;
  },
  async logout(): Promise<void> {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok && response.status !== 204) return parseError(response);
  },
  async approval(
    requestId: string,
    decision: "approve" | "reject",
    reason?: string,
  ): Promise<AnalysisOutcome> {
    const response = await fetch(
      `/analysis/${encodeURIComponent(requestId)}/approval`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ decision, reason: reason || null }),
      },
    );
    if (!response.ok) return parseError(response);
    return response.json() as Promise<AnalysisOutcome>;
  },
};

export async function streamAnalysis(
  payload: {
    request_id: string;
    user_id: string;
    question: string;
    max_rows: number;
  },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/analysis/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) return parseError(response);
  if (!response.body) throw new ApiError("浏览器未收到流式响应。", 502);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as StreamEvent);
    }
    if (done) break;
  }
}

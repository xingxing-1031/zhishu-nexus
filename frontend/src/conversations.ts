import type { AgentResponse, AnalysisOutcome, AnalysisResult, ChartSpec } from "./types";

export const MAX_CONVERSATIONS = 8;
export const MAX_TURNS = 8;

export type StoredStageState = Record<string, "idle" | "running" | "success" | "warning" | "danger" | "skipped">;

export interface FollowUpContext {
  metrics: string[];
  dimensions: string[];
  timeRangeDays: number | null;
  filters: Array<{ field: string; operator: string; value: unknown }>;
  resultColumns: string[];
  answer: string;
}

export interface ConversationTurn {
  id: string;
  requestId: string;
  question: string;
  createdAt: string;
  durationMs: number;
  status: "succeeded" | "degraded" | "answered" | "needs_clarification" | "pending" | "rejected" | "failed";
  summary: string;
  outcome: AnalysisOutcome | null;
  response: AgentResponse | null;
  chartSpec: ChartSpec | null;
  rows: Array<Record<string, unknown>>;
  stageState: StoredStageState;
  followUpContext: FollowUpContext | null;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ConversationTurn[];
}

export interface ConversationAuditSummary {
  total: number;
  succeeded: number;
  degraded: number;
  rejected: number;
  pending: number;
  failed: number;
  averageDurationMs: number;
  lastActiveAt: string | null;
}

const STORAGE_VERSION = 1;

function storageKey(userId: string) {
  return `retail-analytics:conversations:v${STORAGE_VERSION}:${encodeURIComponent(userId)}`;
}

function makeId(prefix: string) {
  const suffix = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

export function newConversation(): Conversation {
  const now = new Date().toISOString();
  return { id: makeId("CONV"), title: "新对话", createdAt: now, updatedAt: now, turns: [] };
}

export function loadConversations(userId: string): Conversation[] {
  try {
    const raw = globalThis.localStorage?.getItem(storageKey(userId));
    if (!raw) return [];
    return normalizeConversations(JSON.parse(raw) as unknown);
  } catch {
    return [];
  }
}

export function normalizeConversations(value: unknown): Conversation[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(normalizeConversation)
    .filter((conversation): conversation is Conversation => conversation !== null)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, MAX_CONVERSATIONS);
}

export function mergeConversations(
  localConversations: Conversation[],
  remoteConversations: Conversation[],
): Conversation[] {
  const byId = new Map(localConversations.map((conversation) => [conversation.id, conversation]));
  remoteConversations.forEach((remote) => {
    const local = byId.get(remote.id);
    byId.set(remote.id, !local || remote.updatedAt >= local.updatedAt ? remote : local);
  });
  return normalizeConversations([...byId.values()]);
}

/**
 * Reconcile a successful account snapshot. Non-empty local records are only
 * an offline fallback; once the account API responds, a missing record means
 * it was deleted or is no longer part of this account's history.
 */
export function reconcileConversations(
  localConversations: Conversation[],
  remoteConversations: Conversation[],
): Conversation[] {
  const remote = normalizeConversations(remoteConversations);
  const localDraft = normalizeConversations(localConversations)
    .find((conversation) => conversation.turns.length === 0);
  const next = localDraft ? [...remote, localDraft] : remote;
  return next.length > 0 ? normalizeConversations(next) : [newConversation()];
}

export function saveConversations(userId: string, conversations: Conversation[]) {
  try {
    const bounded = conversations
      .map((conversation) => ({ ...conversation, turns: conversation.turns.slice(-MAX_TURNS) }))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
      .slice(0, MAX_CONVERSATIONS);
    globalThis.localStorage?.setItem(storageKey(userId), JSON.stringify(bounded));
  } catch {
    // The workspace remains usable when private browsing or storage quotas block persistence.
  }
}

export function appendTurn(conversation: Conversation, turn: ConversationTurn): Conversation {
  return {
    ...conversation,
    title: conversation.turns.length === 0 ? summarizeTitle(turn.question) : conversation.title,
    updatedAt: turn.createdAt,
    turns: [...conversation.turns, turn].slice(-MAX_TURNS),
  };
}

export function replaceTurn(conversation: Conversation, turn: ConversationTurn): Conversation {
  const turns = conversation.turns.map((item) => item.requestId === turn.requestId ? turn : item);
  return { ...conversation, updatedAt: turn.createdAt, turns: turns.slice(-MAX_TURNS) };
}

export function auditSummary(conversation: Conversation): ConversationAuditSummary {
  const totalDuration = conversation.turns.reduce((sum, turn) => sum + turn.durationMs, 0);
  return {
    total: conversation.turns.length,
    succeeded: conversation.turns.filter((turn) => turn.status === "succeeded" || turn.status === "answered").length,
    degraded: conversation.turns.filter((turn) => turn.status === "degraded").length,
    rejected: conversation.turns.filter((turn) => turn.status === "rejected").length,
    pending: conversation.turns.filter((turn) => turn.status === "pending").length,
    failed: conversation.turns.filter((turn) => turn.status === "failed").length,
    averageDurationMs: conversation.turns.length ? Math.round(totalDuration / conversation.turns.length) : 0,
    lastActiveAt: conversation.turns.at(-1)?.createdAt ?? null,
  };
}

export function createStoredTurn(args: {
  requestId: string;
  question: string;
  durationMs: number;
  outcome: AnalysisOutcome | null;
  response: AgentResponse | null;
  failure: string;
  stageState: StoredStageState;
}): ConversationTurn {
  const { outcome } = args;
  const result = isAnalysisResult(outcome) ? outcome : null;
  const safeToPersistRows = Boolean(result?.plan);
  const status = turnStatus(args.failure, outcome, args.response);
  return {
    id: makeId("TURN"),
    requestId: args.requestId,
    question: args.question,
    createdAt: new Date().toISOString(),
    durationMs: args.durationMs,
    status,
    summary: args.failure || outcomeSummary(outcome, args.response),
    outcome: sanitizeOutcome(outcome),
    response: sanitizeAgentResponse(args.response),
    chartSpec: safeToPersistRows ? result?.chart_spec ?? null : null,
    rows: safeToPersistRows ? result?.rows.slice(0, 20) ?? [] : [],
    stageState: args.stageState,
    followUpContext: result?.plan ? buildFollowUpContext(result) : null,
  };
}

export function serializeFollowUpContext(context: FollowUpContext): string {
  const parts = [
    `指标：${context.metrics.join("、") || "未指定"}`,
    `维度：${context.dimensions.join("、") || "不分组"}`,
    `时间：${context.timeRangeDays ? `最近${context.timeRangeDays}天` : "未指定"}`,
    `结果字段：${context.resultColumns.join("、")}`,
    `上一结论：${context.answer.slice(0, 240)}`,
  ];
  return parts.join("；");
}

function sanitizeOutcome(outcome: AnalysisOutcome | null): AnalysisOutcome | null {
  if (!outcome || outcome.status === "pending") return null;
  if (isAnalysisResult(outcome) && !outcome.plan) {
    return { ...outcome, rows: [], chart_spec: null };
  }
  return outcome;
}

function buildFollowUpContext(result: AnalysisResult): FollowUpContext {
  const plan = result.plan!;
  return {
    metrics: plan.metrics,
    dimensions: plan.dimensions,
    timeRangeDays: plan.time_range?.days ?? null,
    filters: plan.filters ?? [],
    resultColumns: result.rows[0] ? Object.keys(result.rows[0]) : [],
    answer: result.answer,
  };
}

function outcomeSummary(outcome: AnalysisOutcome | null, response: AgentResponse | null): string {
  if (!outcome) return response?.answer || response?.report?.executive_summary || "请求未完成";
  if (isAnalysisResult(outcome)) return outcome.answer;
  if (outcome.status === "pending") return "高风险查询正在等待管理员审批";
  if (outcome.status === "rejected") return outcome.reason ?? "请求已被拒绝";
  return outcome.answer;
}

function turnStatus(
  failure: string,
  outcome: AnalysisOutcome | null,
  response: AgentResponse | null,
): ConversationTurn["status"] {
  if (failure) return "failed";
  if (outcome) return outcome.status;
  if (response?.status === "degraded") return "degraded";
  if (response?.status === "refused") return "rejected";
  if (response?.status === "failed") return "failed";
  if (response?.status === "pending") return "pending";
  if (response?.status === "succeeded") return "answered";
  return "failed";
}

function sanitizeAgentResponse(response: AgentResponse | null): AgentResponse | null {
  if (!response) return null;
  return {
    ...response,
    analysis: sanitizeOutcome(response.analysis ?? null),
    exported_report: null,
    knowledge_evidence: response.knowledge_evidence?.slice(0, 8),
    tool_calls: response.tool_calls.slice(0, 12),
  };
}

function summarizeTitle(question: string) {
  const clean = question.replace(/\s+/g, " ").trim();
  return clean.length > 22 ? `${clean.slice(0, 22)}…` : clean || "新对话";
}

function normalizeConversation(value: unknown): Conversation | null {
  if (!isObject(value)) return null;
  if (!isText(value.id) || !isText(value.title) || !isText(value.createdAt) || !isText(value.updatedAt)) return null;
  const turns = Array.isArray(value.turns)
    ? value.turns.map(normalizeTurn).filter((turn): turn is ConversationTurn => turn !== null).slice(-MAX_TURNS)
    : [];
  return {
    id: value.id,
    title: value.title,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    turns,
  };
}

function normalizeTurn(value: unknown): ConversationTurn | null {
  if (!isObject(value)) return null;
  if (!isText(value.id) || !isText(value.requestId) || !isText(value.question) || !isText(value.createdAt)) return null;
  const response = isObject(value.response) ? value.response as unknown as AgentResponse : null;
  const outcome = isObject(value.outcome) ? value.outcome as unknown as AnalysisOutcome : null;
  const summary = isText(value.summary)
    ? value.summary
    : response?.answer || (isAnalysisResult(outcome) ? outcome.answer : "历史回答已恢复");
  return {
    id: value.id,
    requestId: value.requestId,
    question: value.question,
    createdAt: value.createdAt,
    durationMs: typeof value.durationMs === "number" && Number.isFinite(value.durationMs) ? value.durationMs : 0,
    status: isTurnStatus(value.status) ? value.status : "failed",
    summary,
    outcome,
    response,
    chartSpec: isObject(value.chartSpec) ? value.chartSpec as unknown as ChartSpec : null,
    rows: Array.isArray(value.rows)
      ? value.rows.filter(isObject).slice(0, 20)
      : [],
    stageState: isObject(value.stageState) ? value.stageState as StoredStageState : {},
    followUpContext: isObject(value.followUpContext) ? value.followUpContext as unknown as FollowUpContext : null,
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isTurnStatus(value: unknown): value is ConversationTurn["status"] {
  return typeof value === "string" && [
    "succeeded",
    "degraded",
    "answered",
    "needs_clarification",
    "pending",
    "rejected",
    "failed",
  ].includes(value);
}

function isAnalysisResult(outcome: AnalysisOutcome | null): outcome is AnalysisResult {
  return outcome !== null && (outcome.status === "succeeded" || outcome.status === "degraded");
}

import { useEffect, useMemo, useRef, useState } from "react";
import { api, streamAgent } from "./api";
import { assistantFromLiveTurn, assistantFromTurn, type InspectorTab, type LiveTurn } from "./chatModels";
import type { Page } from "./components";
import {
  appendTurn,
  createStoredTurn,
  loadConversations,
  newConversation,
  replaceTurn,
  saveConversations,
  serializeFollowUpContext,
  type FollowUpContext,
  type StoredStageState,
} from "./conversations";
import { localizeUserMessage } from "./localization";
import type {
  AnalysisOutcome,
  AnalysisResult,
  AgentResponse,
  AgentStreamEvent,
  ApprovalRequired,
  Overview,
  SessionInfo,
  TraceEvent,
} from "./types";
import ApprovalSheet from "./workspace/ApprovalSheet";
import ChatThread from "./workspace/ChatThread";
import ConversationRail from "./workspace/ConversationRail";
import EvidenceInspector from "./workspace/EvidenceInspector";
import MessageComposer from "./workspace/MessageComposer";
import WorkspaceHeader from "./workspace/WorkspaceHeader";
import WorkspaceShell from "./workspace/WorkspaceShell";

type StageState = StoredStageState[string];

const analysisStages = [
  "scope",
  "plan",
  "retrieve",
  "generate_sql",
  "validate_sql",
  "validate_business_sql",
  "request_approval",
  "execute_sql",
  "summarize",
] as const;

const stageAliases: Record<string, string> = { assess_risk: "validate_business_sql" };

export default function Workspace({
  session,
  overview,
  ready,
  online,
  onPage,
  onLogout,
}: {
  session: SessionInfo;
  overview: Overview | null;
  ready: boolean;
  online: boolean;
  onPage: (page: Page) => void;
  onLogout: () => void;
}) {
  const initialConversations = useMemo(() => {
    const stored = loadConversations(session.user_id);
    return stored.length ? stored : [newConversation()];
  }, [session.user_id]);
  const [conversations, setConversations] = useState(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState(initialConversations[0].id);
  const [question, setQuestion] = useState("");
  const [maxRows, setMaxRows] = useState(Math.min(10, session.max_rows));
  const [running, setRunning] = useState(false);
  const [liveTurn, setLiveTurn] = useState<LiveTurn | null>(null);
  const [liveConversationId, setLiveConversationId] = useState<string | null>(null);
  const [followUpContext, setFollowUpContext] = useState<FollowUpContext | null>(null);
  const [approval, setApproval] = useState<ApprovalRequired | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("sources");
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceEvent[] | null>(null);
  const [traceError, setTraceError] = useState("");
  const outcomeRef = useRef<AnalysisOutcome | null>(null);
  const responseRef = useRef<AgentResponse | null>(null);
  const stageStateRef = useRef<StoredStageState>({});

  const activeConversation = conversations.find((item) => item.id === activeConversationId) ?? conversations[0];
  const visibleLiveTurn = liveConversationId === activeConversationId ? liveTurn : null;
  const selectedView = useMemo(() => {
    if (!selectedRequestId) return null;
    if (visibleLiveTurn?.requestId === selectedRequestId) return assistantFromLiveTurn(visibleLiveTurn);
    const turn = activeConversation.turns.find((item) => item.requestId === selectedRequestId);
    return turn ? assistantFromTurn(turn) : null;
  }, [activeConversation.turns, selectedRequestId, visibleLiveTurn]);

  useEffect(() => {
    saveConversations(session.user_id, conversations);
  }, [conversations, session.user_id]);

  useEffect(() => {
    const latest = activeConversation.turns.at(-1);
    setSelectedRequestId(latest?.requestId ?? null);
    setTrace(null);
    setTraceError("");
  }, [activeConversationId]);

  async function executeQuestion(rawQuestion: string = question) {
    if (!ready || running || !rawQuestion.trim()) return;
    const displayQuestion = rawQuestion.trim();
    const conversationId = activeConversationId;
    const submittedQuestion = followUpContext
      ? `基于上一轮已验证分析上下文（${serializeFollowUpContext(followUpContext)}），继续回答：${displayQuestion}`
      : displayQuestion;
    const requestId = makeRequestId();
    const startedAt = performance.now();
    const startedAtIso = new Date().toISOString();
    let runFailure = "";

    outcomeRef.current = null;
    responseRef.current = null;
    stageStateRef.current = {};
    setApproval(null);
    setApprovalOpen(false);
    setTrace(null);
    setTraceError("");
    setRunning(true);
    setQuestion("");
    setFollowUpContext(null);
    setLiveConversationId(conversationId);
    setSelectedRequestId(requestId);
    setLiveTurn({
      requestId,
      question: displayQuestion,
      startedAt: startedAtIso,
      statusMessage: "正在理解你的问题",
      outcome: null,
      response: null,
      failure: "",
      stageState: {},
    });

    try {
      await streamAgent(
        {
          request_id: requestId,
          conversation_id: conversationId,
          user_id: session.user_id,
          question: submittedQuestion,
          max_rows: clampRows(maxRows, session.max_rows),
        },
        receiveAgent,
      );
    } catch (reason) {
      runFailure = reason instanceof Error ? localizeUserMessage(reason.message) : "分析请求失败，请稍后重试。";
      setLiveTurn((current) => current ? { ...current, failure: runFailure, statusMessage: "请求未能完成" } : current);
    } finally {
      setRunning(false);
      const storedTurn = createStoredTurn({
        requestId,
        question: displayQuestion,
        durationMs: Math.round(performance.now() - startedAt),
        outcome: outcomeRef.current,
        response: responseRef.current,
        failure: runFailure,
        stageState: stageStateRef.current,
      });
      setConversations((current) => current.map((conversation) => (
        conversation.id === conversationId ? appendTurn(conversation, storedTurn) : conversation
      )));
      setLiveTurn(null);
      setLiveConversationId(null);
    }
  }

  function receiveAgent(event: AgentStreamEvent) {
    setLiveTurn((current) => current ? { ...current, statusMessage: event.message } : current);
    if (event.event === "result" && event.response) {
      const response = event.response;
      const outcome = response.analysis ?? null;
      responseRef.current = response;
      outcomeRef.current = outcome;
      const stages = outcome && "trace" in outcome ? terminalStages(outcome.trace) : {};
      stageStateRef.current = stages;
      setLiveTurn((current) => current ? { ...current, response, outcome, stageState: stages, statusMessage: "任务已完成" } : current);
      if (outcome?.status === "pending") {
        setApproval(outcome);
        setApprovalOpen(true);
      }
    }
    if (event.event === "error") {
      setLiveTurn((current) => current ? { ...current, failure: event.message, statusMessage: "请求未能完成" } : current);
    }
  }

  async function resolveApproval(decision: "approve" | "reject", reason?: string) {
    if (!approval) return;
    const requestId = approval.request_id;
    try {
      const result = await api.approval(requestId, decision, reason);
      setApproval(null);
      setApprovalOpen(false);
      setConversations((current) => current.map((conversation) => {
        const existing = conversation.turns.find((turn) => turn.requestId === requestId);
        if (!existing) return conversation;
        const updatedResponse = updateResponseAfterApproval(existing.response, result);
        const updated = createStoredTurn({
          requestId,
          question: existing.question,
          durationMs: existing.durationMs,
          outcome: result,
          response: updatedResponse,
          failure: "",
          stageState: "trace" in result ? terminalStages(result.trace) : existing.stageState,
        });
        return replaceTurn(conversation, updated);
      }));
      setSelectedRequestId(requestId);
      setInspectorTab("audit");
      setInspectorOpen(true);
    } catch (reasonValue) {
      const message = reasonValue instanceof Error ? localizeUserMessage(reasonValue.message) : "审批处理失败，请稍后重试。";
      setTraceError(message);
    }
  }

  async function loadTrace() {
    if (!selectedRequestId) return;
    setTraceError("");
    try {
      setTrace((await api.trace(selectedRequestId)).events);
    } catch (reason) {
      setTrace([]);
      setTraceError(reason instanceof Error ? localizeUserMessage(reason.message) : "执行记录读取失败。" );
    }
  }

  function inspect(requestId: string, tab: InspectorTab) {
    setSelectedRequestId(requestId);
    setInspectorTab(tab);
    setInspectorOpen(true);
    setTrace(null);
    setTraceError("");
  }

  function createConversation() {
    const conversation = newConversation();
    setConversations((current) => [conversation, ...current].slice(0, 8));
    setActiveConversationId(conversation.id);
    setQuestion("");
    setFollowUpContext(null);
    setRailOpen(false);
  }

  function deleteConversation(id: string) {
    if (!window.confirm("删除这个浏览器中的对话记录？服务端审计记录不会被删除。")) return;
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== id);
      if (remaining.length > 0) {
        if (id === activeConversationId) setActiveConversationId(remaining[0].id);
        return remaining;
      }
      const replacement = newConversation();
      setActiveConversationId(replacement.id);
      return [replacement];
    });
  }

  function followUp(result: AnalysisResult) {
    setFollowUpContext(buildContext(result));
    setQuestion("");
    window.setTimeout(() => document.querySelector<HTMLTextAreaElement>(".message-composer textarea")?.focus(), 0);
  }

  return (
    <main className="workspace-root">
      <a className="skip-link" href="#main-content">跳到对话内容</a>
      <WorkspaceShell
        inspectorOpen={inspectorOpen}
        rail={(
          <ConversationRail
            session={session}
            online={online && ready}
            conversations={conversations}
            activeId={activeConversationId}
            open={railOpen}
            onClose={() => setRailOpen(false)}
            onCreate={createConversation}
            onSelect={setActiveConversationId}
            onDelete={deleteConversation}
            onPage={onPage}
            onLogout={onLogout}
          />
        )}
        header={(
          <WorkspaceHeader
            overview={overview}
            inspectorOpen={inspectorOpen}
            onOpenRail={() => setRailOpen(true)}
            onToggleInspector={() => setInspectorOpen((current) => !current)}
          />
        )}
        thread={(
          <ChatThread
            conversation={activeConversation}
            liveTurn={visibleLiveTurn}
            onAsk={(value) => void executeQuestion(value)}
            onInspect={inspect}
            onFollowUp={followUp}
            onRetry={(value) => void executeQuestion(value)}
            pendingApprovalRequestId={approval?.request_id ?? null}
            onOpenApproval={() => setApprovalOpen(true)}
          />
        )}
        composer={(
          <MessageComposer
            question={question}
            maxRows={maxRows}
            maxAllowedRows={session.max_rows}
            ready={ready}
            running={running}
            followUpContext={followUpContext}
            onQuestion={setQuestion}
            onMaxRows={(value) => setMaxRows(clampRows(value, session.max_rows))}
            onCancelFollowUp={() => setFollowUpContext(null)}
            onSubmit={() => void executeQuestion()}
          />
        )}
        inspector={(
          <EvidenceInspector
            open={inspectorOpen}
            tab={inspectorTab}
            view={selectedView}
            trace={trace}
            traceError={traceError}
            onClose={() => setInspectorOpen(false)}
            onTab={setInspectorTab}
            onLoadTrace={() => void loadTrace()}
          />
        )}
      />
      {approval && approvalOpen && session.role === "admin" && <ApprovalSheet approval={approval} onClose={() => setApprovalOpen(false)} onResolve={resolveApproval} />}
    </main>
  );
}

function terminalStages(traceNodes: string[]): StoredStageState {
  const next = Object.fromEntries(analysisStages.map((name) => [name, "skipped"])) as StoredStageState;
  traceNodes.forEach((node) => {
    const normalized = stageAliases[node] ?? node;
    if (normalized in next && node !== "fail" && node !== "respond") next[normalized] = "success" as StageState;
  });
  return next;
}

function updateResponseAfterApproval(response: AgentResponse | null, result: AnalysisOutcome): AgentResponse | null {
  if (!response) return null;
  const answer = isAnalysisResult(result) ? result.answer : result.status === "rejected" ? result.reason || "请求已拒绝" : response.answer;
  return {
    ...response,
    status: result.status === "succeeded" ? "succeeded" : result.status === "degraded" ? "degraded" : result.status === "rejected" ? "refused" : response.status,
    analysis: result,
    answer,
  };
}

function buildContext(result: AnalysisResult): FollowUpContext {
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

function isAnalysisResult(outcome: AnalysisOutcome): outcome is AnalysisResult {
  return outcome.status === "succeeded" || outcome.status === "degraded";
}

function clampRows(value: number, maximum: number) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(maximum, Math.max(1, Math.trunc(value)));
}

function makeRequestId() {
  const date = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const suffix = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID().slice(0, 8).toUpperCase()
    : Math.random().toString(16).slice(2, 10).toUpperCase();
  return `REQ-${date}-${suffix}`;
}

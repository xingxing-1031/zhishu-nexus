import type { ConversationTurn, StoredStageState } from "./conversations";
import type { AgentResponse, AnalysisOutcome } from "./types";

export type InspectorTab = "sources" | "execution" | "audit";

export interface LiveTurn {
  requestId: string;
  question: string;
  startedAt: string;
  statusMessage: string;
  outcome: AnalysisOutcome | null;
  response: AgentResponse | null;
  failure: string;
  stageState: StoredStageState;
}

export interface AssistantView {
  requestId: string;
  outcome: AnalysisOutcome | null;
  response: AgentResponse | null;
  failure: string;
  statusMessage: string;
  stageState: StoredStageState;
  durationMs: number | null;
  running: boolean;
  status: ConversationTurn["status"] | null;
  fallbackAnswer: string;
}

export function assistantFromTurn(turn: ConversationTurn): AssistantView {
  return {
    requestId: turn.requestId,
    outcome: turn.outcome,
    response: turn.response,
    failure: turn.status === "failed" ? turn.summary : "",
    statusMessage: turn.summary,
    stageState: turn.stageState,
    durationMs: turn.durationMs,
    running: false,
    status: turn.status,
    fallbackAnswer: turn.summary,
  };
}

export function assistantFromLiveTurn(turn: LiveTurn): AssistantView {
  return {
    requestId: turn.requestId,
    outcome: turn.outcome,
    response: turn.response,
    failure: turn.failure,
    statusMessage: turn.statusMessage,
    stageState: turn.stageState,
    durationMs: null,
    running: !turn.failure && turn.response === null,
    status: turn.failure ? "failed" : turn.outcome?.status ?? null,
    fallbackAnswer: "",
  };
}

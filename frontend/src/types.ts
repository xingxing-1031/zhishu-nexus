export type Role = "analyst" | "admin";

export interface SessionInfo {
  user_id: string;
  role: Role;
  public_demo_mode: boolean;
  trace_visible: boolean;
  max_rows: number;
}

export interface Overview {
  order_count: number;
  product_count: number;
  refund_count: number;
  channel_count: number;
  coverage_days: number;
}

export interface AnalysisPlan {
  analysis_goal: string;
  metrics: string[];
  dimensions: string[];
  filters?: Array<{ field: string; operator: string; value: unknown }>;
  time_range?: { days: number } | null;
  sort?: Array<{ field: string; direction: string }>;
  limit: number;
}

export interface ChartSpec {
  chart_type: "bar" | "line" | "kpi";
  title: string;
  x_field?: string | null;
  y_fields: string[];
}

export interface AnalysisResult {
  request_id: string;
  status: "succeeded" | "degraded";
  access_role: Role;
  answer: string;
  plan: AnalysisPlan | null;
  rows: Array<Record<string, unknown>>;
  chart_spec: ChartSpec | null;
  evidence_source_ids: string[];
  retry_count: number;
  degradation_reason?: string | null;
  trace: string[];
}

export interface ApprovalRequired {
  request_id: string;
  status: "pending";
  access_role: Role;
  sql: string;
  sql_fingerprint: string;
  reasons: string[];
  sensitive_columns: string[];
  result_limit: number;
  trace: string[];
}

export interface RejectedResult {
  request_id: string;
  status: "rejected";
  reason?: string;
  reason_code?: string;
  reviewed_by?: string;
  trace: string[];
}

export interface AssistantResult {
  request_id: string;
  status: "answered" | "needs_clarification";
  answer: string;
  reason_code: string;
  trace: string[];
}

export type AnalysisOutcome =
  | AnalysisResult
  | ApprovalRequired
  | RejectedResult
  | AssistantResult;

export interface StreamEvent {
  event: "status" | "result" | "error" | "approval_required" | "rejected" | "assistant_message";
  node?: string | null;
  message: string;
  response?: AnalysisResult | null;
  assistant?: AssistantResult | null;
  approval?: ApprovalRequired | null;
  rejection?: RejectedResult | null;
}

export interface TraceEvent {
  request_id: string;
  component: string;
  status: "started" | "succeeded" | "failed" | "retry_scheduled" | "rejected" | "pending" | "degraded";
  attempt: number;
  occurred_at: string;
  duration_ms?: number | null;
  error_type?: string | null;
  error_message?: string | null;
  retry_delay_ms?: number | null;
}

export interface TraceResponse {
  request_id: string;
  events: TraceEvent[];
}

export interface AuditEntry {
  request_id: string;
  user_id: string;
  access_role: Role;
  original_question: string;
  status: "running" | "succeeded" | "approval_required" | "rejected" | "degraded" | "failed";
  row_count?: number | null;
  duration_ms?: number | null;
  max_rows?: number | null;
  approval_required: boolean;
  created_at: string;
  updated_at: string;
}

export interface MetricDefinition {
  source_id: string;
  name: string;
  version: string;
  description: string;
  formula: string;
  source_tables: string[];
  fixed_rules: string[];
  supported_dimensions: string[];
}

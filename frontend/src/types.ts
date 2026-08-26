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

export type AgentSkillId =
  | "refund_diagnosis"
  | "channel_comparison"
  | "product_analysis"
  | "weekly_report";

export type AgentTaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "degraded"
  | "refused"
  | "failed";

export type AgentMode = "general" | "knowledge" | "data" | "collaboration";
export type ResultDisplayMode = "auto" | "chart_table" | "table";

export interface AgentStep {
  agent: string;
  task: string;
  status: AgentTaskStatus;
}

export interface AgentReview {
  passed: boolean;
  checks: Record<string, boolean>;
  limitations: string[];
}

export interface KnowledgeEvidenceView {
  source_id: string;
  title: string;
  version: string;
  quote: string;
  score: number;
  effective_from?: string | null;
}

export interface AgentSubtask {
  id: string;
  description: string;
  required_tools: string[];
  status: AgentTaskStatus;
}

export interface AgentTaskPlan {
  goal: string;
  skill_id: AgentSkillId;
  subtasks: AgentSubtask[];
  completion_criteria: string[];
  max_steps: number;
}

export interface AgentContextSnapshot {
  conversation_id: string;
  task_goal: string;
  summary: string;
  confirmed_constraints: string[];
  evidence_ids: string[];
  recent_tool_results: string[];
  token_budget: number;
  token_estimate: number;
  truncated: boolean;
}

export interface AgentToolCall {
  request_id: string;
  conversation_id?: string | null;
  tool_name: string;
  input_hash: string;
  status: string;
  duration_ms: number;
  error_type?: string | null;
}

export interface AgentReportFinding {
  statement: string;
  data_evidence_ids: string[];
  document_evidence_ids: string[];
  confidence: string;
}

export interface AgentOperationsReport {
  title: string;
  executive_summary: string;
  findings: AgentReportFinding[];
  charts: Array<Record<string, unknown>>;
  data_evidence: string[];
  document_evidence: string[];
  limitations: string[];
}

export interface AgentResponse {
  request_id: string;
  conversation_id: string;
  status: AgentTaskStatus;
  skill_id?: AgentSkillId | null;
  task_plan?: AgentTaskPlan | null;
  context?: AgentContextSnapshot | null;
  analysis?: AnalysisOutcome | null;
  report?: AgentOperationsReport | null;
  exported_report?: string | null;
  tool_calls: AgentToolCall[];
  limitations: string[];
  agent_mode?: AgentMode | null;
  agents?: string[];
  agent_steps?: AgentStep[];
  answer?: string;
  knowledge_evidence?: KnowledgeEvidenceView[];
  review?: AgentReview | null;
}

export interface AgentStreamEvent {
  event: "status" | "result" | "error";
  node?: string | null;
  message: string;
  response?: AgentResponse | null;
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
  conversation_id?: string | null;
  user_id: string;
  access_role: Role;
  agent_mode: AgentMode;
  original_question: string;
  status: "running" | "succeeded" | "approval_required" | "rejected" | "degraded" | "failed";
  row_count?: number | null;
  duration_ms?: number | null;
  max_rows?: number | null;
  approval_required: boolean;
  tool_names: string[];
  evidence_count: number;
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

export type DatasetStatus =
  | "uploaded"
  | "profiling"
  | "needs_mapping"
  | "ready"
  | "failed"
  | "archived";

export interface DatasetRecord {
  dataset_id: string;
  dataset_name: string;
  source_type: string;
  source_ref: string | null;
  schema_name: string;
  version: number;
  status: DatasetStatus;
  row_count: number;
  quality_report: Record<string, unknown> | null;
  mapping: Record<string, unknown> | null;
  mapping_confirmed: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface QualityIssue {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  table: string;
  column?: string | null;
}

export interface QualityReportView {
  passed: boolean;
  checked_rows: number;
  issues: QualityIssue[];
}

export interface ImportResultView {
  dataset_id: string;
  version: number;
  schema_name: string;
  tables: string[];
  row_counts: Record<string, number>;
}

export interface ColumnProfileView {
  name: string;
  normalized_type: string;
  null_ratio: number;
  unique_ratio: number;
  sample_values: Array<unknown>;
  candidate_roles: string[];
}

export interface TableProfileView {
  table_name: string;
  row_count: number;
  columns: ColumnProfileView[];
}

export interface SchemaProfileView {
  schema_name: string;
  tables: TableProfileView[];
}

export interface MappingFieldView {
  role: string;
  table: string;
  column: string;
  confidence: number;
  reasons: string[];
}

export interface DatasetMappingView {
  dataset_id: string;
  version: number;
  mapping_version: string;
  fields: MappingFieldView[];
  confirmed: boolean;
}

export interface DatasetProfile {
  dataset: DatasetRecord;
  import_result: ImportResultView;
  schema: SchemaProfileView;
  mapping: DatasetMappingView;
  quality: QualityReportView;
}

export interface DatasetMetricView {
  metric_id: string;
  name: string;
  version: string;
  definition: string;
  formula: string;
  source_table: string;
  source_column: string;
  supported_dimensions: string[];
  status: "proposed" | "confirmed" | "archived";
}

export interface DatasetMetric {
  dataset_id: string;
  dataset_version: number;
  metric_id: string;
  metric_version: string;
  name: string;
  definition: string;
  aggregation: string;
  formula: string;
  source_role: string;
  source_table: string;
  source_column: string;
  supported_dimensions: string[];
  fixed_filters: string[];
  status: "proposed" | "confirmed" | "archived";
  effective_from?: string | null;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
}

export interface MetricProposals {
  dataset_id: string;
  version: number;
  metrics: DatasetMetric[];
}

export interface DatasetView {
  dataset_id: string;
  dataset_name: string;
  version: number;
  source_type: string;
  row_count: number;
  schema_name: string;
  status: DatasetStatus;
  metrics: Array<{
    metric_id: string;
    name: string;
    version: string;
    definition: string;
    formula: string;
    source_table: string;
    source_column: string;
    supported_dimensions: string[];
  }>;
}

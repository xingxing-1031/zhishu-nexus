import {
  BookOpenText,
  Clock3,
  Code2,
  FileSearch,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import type { AssistantView, InspectorTab } from "../chatModels";
import { EmptyState, StatusPill, outcomeVisualStatus } from "../components";
import { label, localizeEvidence, traceComponentLabels } from "../localization";
import type { AnalysisResult, TraceEvent } from "../types";

export default function EvidenceInspector({
  open,
  tab,
  view,
  trace,
  traceError,
  onClose,
  onTab,
  onLoadTrace,
}: {
  open: boolean;
  tab: InspectorTab;
  view: AssistantView | null;
  trace: TraceEvent[] | null;
  traceError: string;
  onClose: () => void;
  onTab: (tab: InspectorTab) => void;
  onLoadTrace: () => void;
}) {
  const response = view?.response ?? null;
  const analysis = getAnalysis(view);
  return (
    <>
      {open && <button className="inspector-scrim" type="button" onClick={onClose} aria-label="关闭证据面板" />}
      <aside className={`evidence-inspector ${open ? "open" : ""}`} aria-label="证据与执行详情">
        <header className="inspector-header">
          <div><strong>任务详情</strong><small>{view?.requestId ?? "选择一条企析回答"}</small></div>
          <button type="button" onClick={onClose} aria-label="关闭证据面板" title="关闭"><X size={18} /></button>
        </header>
        <div className="inspector-tabs" role="tablist" aria-label="任务详情分类">
          <button className={tab === "sources" ? "active" : ""} type="button" role="tab" aria-selected={tab === "sources"} onClick={() => onTab("sources")}><FileSearch size={15} />引用</button>
          <button className={tab === "execution" ? "active" : ""} type="button" role="tab" aria-selected={tab === "execution"} onClick={() => onTab("execution")}><Clock3 size={15} />执行</button>
          <button className={tab === "audit" ? "active" : ""} type="button" role="tab" aria-selected={tab === "audit"} onClick={() => onTab("audit")}><ShieldCheck size={15} />审计</button>
        </div>
        <div className="inspector-body">
          {!view ? <EmptyState>从一条企析回答中打开引用、执行过程或请求详情</EmptyState> : tab === "sources" ? (
            <SourcesPanel view={view} analysis={analysis} />
          ) : tab === "execution" ? (
            <ExecutionPanel view={view} trace={trace} traceError={traceError} onLoadTrace={onLoadTrace} />
          ) : (
            <AuditPanel view={view} analysis={analysis} />
          )}
        </div>
      </aside>
    </>
  );
}

function SourcesPanel({ view, analysis }: { view: AssistantView; analysis: AnalysisResult | null }) {
  const response = view.response;
  const knowledge = response?.knowledge_evidence ?? [];
  const dataEvidence = response?.report?.data_evidence ?? analysis?.evidence_source_ids ?? [];
  if (knowledge.length === 0 && dataEvidence.length === 0) return <EmptyState>这条回答不依赖企业知识或经营数据证据</EmptyState>;
  return (
    <div className="inspector-stack">
      {knowledge.length > 0 && <section className="inspector-section"><div className="inspector-section-title"><BookOpenText size={15} /><strong>企业知识引用</strong><span>{knowledge.length}</span></div><div className="source-list">{knowledge.map((item) => <blockquote key={item.source_id}><strong>{item.title}</strong><span>v{item.version}{item.effective_from ? ` · 生效 ${item.effective_from.slice(0, 10)}` : ""}</span><p>{item.quote}</p><small>相关度 {(item.score * 100).toFixed(0)}%</small></blockquote>)}</div></section>}
      {dataEvidence.length > 0 && <section className="inspector-section"><div className="inspector-section-title"><Code2 size={15} /><strong>数据证据</strong><span>{dataEvidence.length}</span></div><ul className="evidence-id-list">{dataEvidence.map((item) => <li key={item}><code>{localizeEvidence(item)}</code></li>)}</ul></section>}
    </div>
  );
}

function ExecutionPanel({ view, trace, traceError, onLoadTrace }: { view: AssistantView; trace: TraceEvent[] | null; traceError: string; onLoadTrace: () => void }) {
  const response = view.response;
  const steps = response?.agent_steps ?? [];
  const tools = response?.tool_calls ?? [];
  return (
    <div className="inspector-stack">
      <section className="inspector-section">
        <div className="inspector-section-title"><Clock3 size={15} /><strong>Agent 协作</strong><span>{steps.length}</span></div>
        {steps.length ? <ol className="inspector-timeline">{steps.map((step, index) => <li key={`${step.agent}-${index}`}><span className={`timeline-dot ${step.status}`} /><div><strong>{agentLabel(step.agent)}</strong><p>{step.task}</p></div><small>{statusLabel(step.status)}</small></li>)}</ol> : <EmptyState>{view.running ? view.statusMessage : "本次任务没有记录多 Agent 步骤"}</EmptyState>}
      </section>
      <section className="inspector-section">
        <div className="inspector-section-title"><Code2 size={15} /><strong>工具调用</strong><span>{tools.length}</span></div>
        {tools.length ? <ul className="tool-call-list">{tools.map((tool, index) => <li key={`${tool.tool_name}-${index}`}><div><strong>{toolLabel(tool.tool_name)}</strong><small>{tool.status === "succeeded" ? "调用成功" : tool.status}</small></div><code>{tool.duration_ms} ms</code></li>)}</ul> : <EmptyState>本次回答不需要调用外部工具</EmptyState>}
      </section>
      <section className="inspector-section">
        <div className="inspector-section-title"><RefreshCw size={15} /><strong>节点记录</strong><button type="button" onClick={onLoadTrace}>读取</button></div>
        {traceError ? <div className="inspector-error">{traceError}</div> : trace === null ? <p className="inspector-note">按需读取服务端节点、耗时和重试记录。</p> : trace.length === 0 ? <EmptyState>当前请求没有可查看的节点记录</EmptyState> : <ul className="trace-list">{trace.map((event, index) => <li key={`${event.component}-${index}`}><div><strong>{traceComponentLabels[event.component] ?? event.component}</strong><small>{new Date(event.occurred_at).toLocaleTimeString("zh-CN", { hour12: false })}</small></div><StatusPill status={outcomeVisualStatus(event.status)}>{traceStatusLabel(event.status)}</StatusPill><code>{event.duration_ms == null ? "—" : `${event.duration_ms} ms`}</code></li>)}</ul>}
      </section>
    </div>
  );
}

function AuditPanel({ view, analysis }: { view: AssistantView; analysis: AnalysisResult | null }) {
  const response = view.response;
  return (
    <div className="inspector-stack">
      <section className="inspector-section request-audit-summary">
        <div><span>请求编号</span><code>{view.requestId}</code></div>
        <div><span>执行模式</span><strong>{modeLabel(response?.agent_mode)}</strong></div>
        <div><span>耗时</span><strong className="mono">{view.durationMs == null ? "执行中" : `${(view.durationMs / 1000).toFixed(2)}s`}</strong></div>
        <div><span>审核</span><strong>{response?.review ? response.review.passed ? "通过" : "存在限制" : "未提供"}</strong></div>
      </section>
      {analysis?.plan && <section className="inspector-section"><div className="inspector-section-title"><ShieldCheck size={15} /><strong>分析口径</strong></div><dl className="audit-definition-list"><div><dt>指标</dt><dd>{analysis.plan.metrics.map(label).join("、")}</dd></div><div><dt>维度</dt><dd>{analysis.plan.dimensions.map(label).join("、") || "不分组"}</dd></div><div><dt>时间</dt><dd>{analysis.plan.time_range ? `最近 ${analysis.plan.time_range.days} 天` : "未指定"}</dd></div><div><dt>返回</dt><dd>最多 {analysis.plan.limit} 条</dd></div></dl></section>}
      {response?.review && <section className="inspector-section"><div className="inspector-section-title"><ShieldCheck size={15} /><strong>审核检查</strong></div><ul className="review-check-list">{Object.entries(response.review.checks).map(([name, passed]) => <li key={name}><span>{passed ? "通过" : "未通过"}</span><code>{name}</code></li>)}</ul></section>}
      {(response?.limitations.length ?? 0) > 0 && <section className="inspector-section"><div className="inspector-section-title"><ShieldCheck size={15} /><strong>限制说明</strong></div><ul className="inspector-plain-list">{response!.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>}
    </div>
  );
}

function getAnalysis(view: AssistantView | null): AnalysisResult | null {
  const outcome = view?.response?.analysis ?? view?.outcome ?? null;
  return outcome && (outcome.status === "succeeded" || outcome.status === "degraded") ? outcome : null;
}

function modeLabel(mode?: string | null) {
  return ({ general: "通用对话", knowledge: "企业知识", data: "经营数据", collaboration: "知识与数据协作" } as Record<string, string>)[mode ?? ""] ?? "自动路由";
}

function agentLabel(agent: string) {
  return ({ general_agent: "通用 Agent", knowledge_agent: "知识 Agent", data_agent: "数据 Agent", synthesis_agent: "综合 Agent", review_agent: "审核 Agent" } as Record<string, string>)[agent] ?? agent;
}

function toolLabel(tool: string) {
  return ({ "time.now": "时间查询", "weather.current": "天气查询", "web.search": "网页搜索", "web.fetch_summary": "网页摘要", "exchange.rate": "汇率查询", "knowledge.search": "知识检索", "sql.query": "受控数据查询", "report.export": "报告导出" } as Record<string, string>)[tool] ?? tool;
}

function statusLabel(status: string) {
  return ({ succeeded: "完成", degraded: "降级", pending: "等待", refused: "拒绝", failed: "失败", running: "执行中" } as Record<string, string>)[status] ?? status;
}

function traceStatusLabel(status: string) {
  return ({ started: "开始", succeeded: "成功", failed: "失败", retry_scheduled: "等待重试", rejected: "拒绝", pending: "等待审批", degraded: "降级" } as Record<string, string>)[status] ?? status;
}

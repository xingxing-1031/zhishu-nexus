import {
  BarChart3,
  BrainCircuit,
  Check,
  ChevronRight,
  Clock3,
  Database,
  FileSearch,
  FileOutput,
  ListChecks,
  Play,
  ShieldAlert,
  TableProperties,
} from "lucide-react";
import { FormEvent, lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { api, streamAgent, streamAnalysis } from "./api";
import ConversationPanel from "./ConversationPanel";
import {
  appendTurn,
  createStoredTurn,
  loadConversations,
  newConversation,
  replaceTurn,
  saveConversations,
  serializeFollowUpContext,
  type Conversation,
  type ConversationTurn,
  type FollowUpContext,
  type StoredStageState,
} from "./conversations";
import {
  Drawer,
  EmptyState,
  KpiCard,
  StatusPill,
  TrustCard,
  outcomeVisualStatus,
} from "./components";
import { formatValue, label, localizeAnswer, localizeEvidence, localizeUserMessage, traceComponentLabels } from "./localization";
import type {
  AnalysisOutcome,
  AnalysisResult,
  AgentResponse,
  AgentStreamEvent,
  ApprovalRequired,
  Overview,
  SessionInfo,
  StreamEvent,
  TraceEvent,
} from "./types";

const ResultChart = lazy(() => import("./ResultChart"));

const stages = [
  ["scope", "范围识别"],
  ["plan", "计划"],
  ["retrieve", "证据检索"],
  ["generate_sql", "查询生成"],
  ["validate_sql", "安全校验"],
  ["validate_business_sql", "业务校验"],
  ["request_approval", "审批确认"],
  ["execute_sql", "数据执行"],
  ["summarize", "结论生成"],
] as const;

const stageAliases: Record<string, string> = {
  assess_risk: "validate_business_sql",
};

const examples = [
  ["渠道经营", "统计最近30天各销售渠道的销售额，按销售额从高到低排序，返回10条。"],
  ["商品表现", "最近30天各商品销量从高到低排列，返回10条。"],
  ["售后风险", "最近30天各退款状态的退款金额是多少？"],
  ["趋势分析", "最近30天按日期统计销售额变化趋势。"],
];

type StageState = "idle" | "running" | "success" | "warning" | "danger" | "skipped";
type WorkspaceMode = "query" | "agent";

export default function Workspace({
  session,
  overview,
  ready,
}: {
  session: SessionInfo;
  overview: Overview | null;
  ready: boolean;
}) {
  const [question, setQuestion] = useState(examples[0][1]);
  const [mode, setMode] = useState<WorkspaceMode>("agent");
  const [maxRows, setMaxRows] = useState(Math.min(10, session.max_rows));
  const [requestId, setRequestId] = useState("");
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("选择一个经营场景，或输入你的业务问题");
  const [outcome, setOutcome] = useState<AnalysisOutcome | null>(null);
  const [agentResponse, setAgentResponse] = useState<AgentResponse | null>(null);
  const [failure, setFailure] = useState("");
  const [approval, setApproval] = useState<ApprovalRequired | null>(null);
  const [trace, setTrace] = useState<TraceEvent[] | null>(null);
  const [traceError, setTraceError] = useState("");
  const [stageState, setStageState] = useState<Record<string, StageState>>({});
  const initialConversations = useMemo(() => {
    const stored = loadConversations(session.user_id);
    return stored.length ? stored : [newConversation()];
  }, [session.user_id]);
  const [conversations, setConversations] = useState<Conversation[]>(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState(initialConversations[0].id);
  const [followUpContext, setFollowUpContext] = useState<FollowUpContext | null>(null);
  const outcomeRef = useRef<AnalysisOutcome | null>(null);
  const stageStateRef = useRef<Record<string, StageState>>({});

  const analysis = isAnalysisResult(outcome) ? outcome : null;
  const elapsed = useMemo(
    () => trace?.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0) ?? null,
    [trace],
  );

  useEffect(() => {
    saveConversations(session.user_id, conversations);
  }, [conversations, session.user_id]);

  function resetRun() {
    setOutcome(null);
    setAgentResponse(null);
    setFailure("");
    setApproval(null);
    setTrace(null);
    setTraceError("");
    updateStages({});
    outcomeRef.current = null;
  }

  function updateStages(next: Record<string, StageState>) {
    stageStateRef.current = next;
    setStageState(next);
  }

  function markStage(node: string, state: StageState = "success") {
    const normalized = stageAliases[node] ?? node;
    if (!stages.some(([name]) => name === normalized)) return;
    updateStages({ ...stageStateRef.current, [normalized]: state });
  }

  function terminalStages(traceNodes: string[], terminalNode?: string, terminalState: StageState = "danger") {
    const next = Object.fromEntries(stages.map(([name]) => [name, "skipped"])) as Record<string, StageState>;
    traceNodes.forEach((node) => {
      const normalized = stageAliases[node] ?? node;
      if (normalized in next && node !== "fail" && node !== "respond") next[normalized] = "success";
    });
    if (terminalNode) {
      const normalized = stageAliases[terminalNode] ?? terminalNode;
      if (normalized in next) next[normalized] = terminalState;
    }
    updateStages(next);
  }

  function receive(event: StreamEvent) {
    setMessage(localizeUserMessage(event.message));
    if (event.event === "status" && event.node) markStage(event.node, "success");
    if (event.event === "result" && event.response) {
      outcomeRef.current = event.response;
      setOutcome(event.response);
      terminalStages(event.response.trace);
    } else if (event.event === "assistant_message" && event.assistant) {
      outcomeRef.current = event.assistant;
      setOutcome(event.assistant);
      terminalStages(event.assistant.trace);
    } else if (event.event === "approval_required" && event.approval) {
      outcomeRef.current = event.approval;
      setOutcome(event.approval);
      setApproval(event.approval);
      terminalStages(event.approval.trace, "request_approval", "warning");
    } else if (event.event === "rejected" && event.rejection) {
      outcomeRef.current = event.rejection;
      setOutcome(event.rejection);
      terminalStages(event.rejection.trace, event.node ?? "scope");
    } else if (event.event === "error") {
      setFailure(event.message);
      if (event.node) markStage(event.node, "danger");
    }
  }

  async function run(event: FormEvent) {
    event.preventDefault();
    await executeQuestion(question);
  }

  function receiveAgent(event: AgentStreamEvent) {
    setMessage(event.message);
    if (event.event === "result" && event.response) {
      setAgentResponse(event.response);
    }
    if (event.event === "error") setFailure(event.message);
  }

  async function executeQuestion(nextQuestion: string) {
    if (!ready || running || !nextQuestion.trim()) return;
    const displayQuestion = nextQuestion.trim();
    const submittedQuestion = followUpContext
      ? `基于上一轮已验证分析上下文（${serializeFollowUpContext(followUpContext)}），继续回答：${displayQuestion}`
      : displayQuestion;
    const nextRequestId = makeRequestId();
    const startedAt = performance.now();
    let runFailure = "";
    resetRun();
    setRunning(true);
    setMessage("分析请求已发送");
    setRequestId(nextRequestId);
    try {
      if (mode === "agent") {
        await streamAgent(
          {
            request_id: nextRequestId,
            conversation_id: activeConversationId,
            user_id: session.user_id,
            question: submittedQuestion,
            max_rows: clampRows(maxRows, session.max_rows),
          },
          receiveAgent,
        );
      } else {
        await streamAnalysis(
          {
            request_id: nextRequestId,
            user_id: session.user_id,
            question: submittedQuestion,
            max_rows: clampRows(maxRows, session.max_rows),
          },
          receive,
        );
      }
    } catch (reason) {
      runFailure = reason instanceof Error ? localizeUserMessage(reason.message) : "分析请求失败，请稍后重试。";
      setFailure(runFailure);
      setMessage("请求未能完成");
    } finally {
      setRunning(false);
      setFollowUpContext(null);
      const turn = createStoredTurn({
        requestId: nextRequestId,
        question: displayQuestion,
        durationMs: Math.round(performance.now() - startedAt),
        outcome: outcomeRef.current,
        failure: runFailure,
        stageState: stageStateRef.current as StoredStageState,
      });
      setConversations((current) => current.map((conversation) => (
        conversation.id === activeConversationId ? appendTurn(conversation, turn) : conversation
      )));
    }
  }

  async function resolveApproval(decision: "approve" | "reject", reason?: string) {
    if (!approval) return;
    setMessage(decision === "approve" ? "正在恢复请求" : "正在记录拒绝结果");
    try {
      const result = await api.approval(approval.request_id, decision, reason);
      outcomeRef.current = result;
      setOutcome(result);
      setApproval(null);
      setFailure("");
      if (isAnalysisResult(result)) {
        setMessage("分析完成");
        terminalStages(result.trace);
      } else {
        setMessage(result.status === "rejected" ? "审批已拒绝" : "审批处理完成");
        terminalStages(result.trace, "request_approval", "danger");
      }
      const currentConversation = conversations.find((conversation) => conversation.id === activeConversationId);
      const existingTurn = currentConversation?.turns.find((turn) => turn.requestId === approval.request_id);
      if (existingTurn) {
        const updatedTurn = createStoredTurn({
          requestId: approval.request_id,
          question: existingTurn.question,
          durationMs: existingTurn.durationMs,
          outcome: result,
          failure: "",
          stageState: stageStateRef.current as StoredStageState,
        });
        setConversations((current) => current.map((conversation) => (
          conversation.id === activeConversationId ? replaceTurn(conversation, updatedTurn) : conversation
        )));
      }
    } catch (error) {
      setFailure(error instanceof Error ? localizeUserMessage(error.message) : "审批处理失败，请稍后重试。");
    }
  }

  async function openTrace() {
    if (!requestId) return;
    setTraceError("");
    try {
      setTrace((await api.trace(requestId)).events);
    } catch (error) {
      setTrace([]);
      setTraceError(error instanceof Error ? localizeUserMessage(error.message) : "执行记录读取失败。");
    }
  }

  function createConversation() {
    const conversation = newConversation();
    setConversations((current) => [conversation, ...current].slice(0, 8));
    setActiveConversationId(conversation.id);
    setQuestion("");
    setFollowUpContext(null);
    resetRun();
  }

  function deleteConversation(id: string) {
    if (!window.confirm("删除这个浏览器中的对话记录？服务端审计记录不会被删除。")) return;
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== id);
      if (remaining.length) {
        if (id === activeConversationId) setActiveConversationId(remaining[0].id);
        return remaining;
      }
      const replacement = newConversation();
      setActiveConversationId(replacement.id);
      return [replacement];
    });
    resetRun();
  }

  function restoreTurn(turn: ConversationTurn) {
    setRequestId(turn.requestId);
    setQuestion(turn.question);
    setOutcome(turn.outcome);
    outcomeRef.current = turn.outcome;
    setFailure(turn.status === "failed" ? turn.summary : "");
    updateStages(turn.stageState);
    setMessage(`已恢复 ${new Date(turn.createdAt).toLocaleString("zh-CN", { hour12: false })} 的记录`);
    setFollowUpContext(null);
  }

  return (
    <main className="workspace-page">
      <section className="kpi-strip" aria-label="业务数据概况">
        <KpiCard label="订单数量" value={overview?.order_count.toLocaleString("zh-CN") ?? "—"} />
        <KpiCard label="商品数量" value={overview?.product_count.toLocaleString("zh-CN") ?? "—"} />
        <KpiCard label="销售渠道" value={overview ? `${overview.channel_count} 个` : "—"} />
        <KpiCard label="退款记录" value={overview ? `${overview.refund_count} 条` : "—"} />
        <KpiCard label="数据覆盖时间" value={overview ? `${overview.coverage_days} 天` : "—"} />
        <TrustCard publicDemo={session.public_demo_mode} />
      </section>

      <div className="workspace-layout">
        <div className="workspace-sidebar">
          <ConversationPanel
            conversations={conversations}
            activeId={activeConversationId}
            onCreate={createConversation}
            onSelect={(id) => { setActiveConversationId(id); resetRun(); setFollowUpContext(null); }}
            onDelete={deleteConversation}
            onSelectTurn={restoreTurn}
          />
          <aside className="query-panel">
          <div className="mode-switch" role="tablist" aria-label="分析模式">
            <button type="button" className={mode === "agent" ? "active" : ""} onClick={() => { setMode("agent"); resetRun(); }}><BrainCircuit size={15} /> Agent 复盘</button>
            <button type="button" className={mode === "query" ? "active" : ""} onClick={() => { setMode("query"); resetRun(); }}><Database size={15} /> 受控查询</button>
          </div>
          <h2>{mode === "agent" ? "经营复盘" : "提问分析"}</h2>
          <p className="panel-intro">{mode === "agent" ? "由 Skill 规划任务，联合数据库与企业制度证据。" : "直接运行只读、可审计的结构化数据查询。"}</p>
          <form onSubmit={run}>
            <label htmlFor="question">业务问题</label>
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="请输入你的业务问题，例如：最近30天各渠道销售额排名"
              rows={5}
              maxLength={800}
              required
            />
            <span className="field-label">示例场景</span>
            <div className="scenario-grid">
              {examples.map(([name, value]) => (
                <button key={name} type="button" onClick={() => setQuestion(value)}>
                  {name}
                </button>
              ))}
            </div>
            <div className="number-field">
              <label htmlFor="maxRows">最大返回行数</label>
              <div>
                <input
                  id="maxRows"
                  className="mono"
                  type="number"
                  min={1}
                  max={session.max_rows}
                  value={maxRows}
                  onChange={(event) => setMaxRows(clampRows(Number(event.target.value), session.max_rows))}
                />
                <span>条</span>
              </div>
            </div>
            <p className="field-help">公开演示最多 {session.max_rows} 条；聚合分析通常返回 10 条即可。</p>
            {followUpContext && (
              <div className="context-chip">
                <span>正在基于上一结果追问</span>
                <button type="button" onClick={() => setFollowUpContext(null)}>取消</button>
              </div>
            )}
            <button className="primary-button run-button" type="submit" disabled={!ready || running}>
              {running ? <Clock3 size={16} /> : <Play size={16} />}
              {running ? "分析进行中" : ready ? "运行分析" : "数据服务正在准备"}
            </button>
          </form>
          <div className="request-number">
            <span>请求编号</span>
            <code>{requestId || "尚未创建"}</code>
          </div>
          </aside>
        </div>

        <section className="analysis-content">
          {mode === "agent" && <AgentPanel response={agentResponse} running={running} />}
          <section className="workflow-card" aria-labelledby="workflow-heading">
            <div className="section-title-row">
              <div>
                <h2 id="workflow-heading">分析工作流</h2>
                <p>{message}</p>
              </div>
              <span className="mono">{elapsed === null ? "等待运行" : `总耗时 ${(elapsed / 1000).toFixed(2)}s`}</span>
            </div>
            <ol className="workflow-list">
              {stages.map(([name, display]) => (
                <li key={name} className={stageState[name] ?? "idle"}>
                  <span className="workflow-icon">
                    {stageState[name] === "success" ? <Check size={13} /> : stageState[name] === "skipped" ? "—" : stages.findIndex(([item]) => item === name) + 1}
                  </span>
                  <span>{display}</span>
                  <ChevronRight className="workflow-arrow" size={13} />
                </li>
              ))}
            </ol>
          </section>

          <section className="conclusion-card">
            <div className="section-title-row">
              <div>
                <h2>{analysis?.plan?.analysis_goal ? localizeAnswer(analysis.plan.analysis_goal) : (analysis ? "受控数据查询结果" : outcome ? "助手答复与边界说明" : "经营分析结论")}</h2>
                <p>{analysis ? "只展示数据库结果和经过约束的业务解释" : "简单问题直接答复，业务查询才进入受控数据链路"}</p>
              </div>
              <div className="conclusion-actions">
                <OutcomePill outcome={outcome} failure={failure} running={running} />
                {session.trace_visible && requestId && (
                  <button className="text-button" type="button" onClick={openTrace}>
                    查看执行记录
                  </button>
                )}
                {analysis?.plan && (
                  <button className="secondary-button compact-button" type="button" onClick={() => { setFollowUpContext(buildContext(analysis)); setQuestion(""); }}>
                    基于此结果继续
                  </button>
                )}
              </div>
            </div>
            <Conclusion outcome={outcome} failure={failure} />
            {analysis?.plan ? (
              <div className="conclusion-meta">
                <span>指标：{analysis.plan.metrics.map(label).join("、")}</span>
                <span>口径：版本化指标字典</span>
                <span>时间：{analysis.plan.time_range ? `最近${analysis.plan.time_range.days}天（业务时区）` : "未指定"}</span>
              </div>
            ) : analysis ? (
              <div className="conclusion-meta">
                <span>类型：经审批的受控字段查询</span>
                <span>结果：{analysis.rows.length} 条</span>
              </div>
            ) : null}
          </section>

          {(!outcome || analysis) && <div className="result-grid">
            <section className="data-card">
              <div className="card-heading">
                <div><BarChart3 size={16} /><h2>数据图表</h2></div>
                <span>{analysis ? (analysis.chart_spec?.title ? localizeAnswer(analysis.chart_spec.title) : "无需绘图") : "等待分析"}</span>
              </div>
              {analysis?.chart_spec ? (
                <Suspense fallback={<EmptyState>正在准备数据图表</EmptyState>}>
                  <ResultChart spec={analysis.chart_spec} rows={analysis.rows} />
                </Suspense>
              ) : <EmptyState>当前结果不适合绘制图表，先查看结果表格</EmptyState>}
            </section>
            <section className="data-card">
              <div className="card-heading">
                <div><TableProperties size={16} /><h2>结果表格</h2></div>
                <span className="mono">{analysis?.rows.length ?? 0} 条结果</span>
              </div>
              <ResultTable rows={analysis?.rows ?? []} />
            </section>
          </div>}

          {(!outcome || analysis) && <section className="evidence-card" id="audit-evidence" aria-labelledby="evidence-heading">
            <div className="card-heading">
              <div><FileSearch size={16} /><h2 id="evidence-heading">审计依据</h2></div>
              <span>{analysis && !analysis.plan ? "本次查询的审批、SQL 与结果记录可追溯" : "本次分析的计划、证据与口径可追溯"}</span>
            </div>
            <div className="evidence-grid">
              <EvidenceColumn icon={<Database size={15} />} title="分析计划">
                {analysis?.plan ? <PlanView result={analysis} /> : <EmptyState>{analysis ? "此请求为受控字段查询，不使用指标分析计划" : "本次请求还没有分析计划"}</EmptyState>}
              </EvidenceColumn>
              <EvidenceColumn icon={<FileSearch size={15} />} title="检索证据">
                {analysis?.evidence_source_ids.length ? (
                  <ul className="plain-list">
                    {analysis.evidence_source_ids.map((source) => <li key={source}>{localizeEvidence(source)}</li>)}
                  </ul>
                ) : <EmptyState>本次请求没有生成可展示的业务证据</EmptyState>}
              </EvidenceColumn>
              <EvidenceColumn icon={<ShieldAlert size={15} />} title="业务口径约束">
                {analysis && !analysis.plan ? (
                  <ul className="plain-list">
                    <li>敏感字段仅限管理员审批后读取</li>
                    <li>实际执行 SQL 与审批预览保持一致</li>
                    <li>查询为只读且限制返回行数</li>
                    <li>审批行为与查询结果已写入审计记录</li>
                  </ul>
                ) : (
                  <ul className="plain-list">
                    <li>销售额使用订单明细成交价快照</li>
                    <li>固定统计已支付订单</li>
                    <li>日期按 Asia/Shanghai 解释</li>
                    <li>SQL 通过只读和业务一致性校验</li>
                  </ul>
                )}
              </EvidenceColumn>
            </div>
          </section>}
        </section>
      </div>

      {approval && session.role === "admin" && (
        <ApprovalDrawer approval={approval} onClose={() => setApproval(null)} onResolve={resolveApproval} />
      )}
      {trace !== null && (
        <TraceDrawer requestId={requestId} events={trace} error={traceError} onClose={() => setTrace(null)} />
      )}
    </main>
  );
}

function OutcomePill({ outcome, failure, running }: { outcome: AnalysisOutcome | null; failure: string; running: boolean }) {
  if (running) return <StatusPill status="running">分析中</StatusPill>;
  if (failure) return <StatusPill status="danger">执行失败</StatusPill>;
  if (!outcome) return <StatusPill status="neutral">尚未运行</StatusPill>;
  if (isAnalysisResult(outcome)) return <StatusPill status={outcome.status === "degraded" ? "warning" : "success"}>{outcome.status === "degraded" ? "查询降级" : "查询成功"}</StatusPill>;
  if (outcome.status === "pending") return <StatusPill status="warning">等待审批</StatusPill>;
  if (outcome.status === "rejected") return <StatusPill status="danger">已拒绝</StatusPill>;
  return <StatusPill status="neutral">助手答复</StatusPill>;
}

function Conclusion({ outcome, failure }: { outcome: AnalysisOutcome | null; failure: string }) {
  if (failure) return <div className="result-message danger"><strong>本次请求未能完成</strong><p>{failure}</p><span>可以检查服务状态后重新分析，系统不会自动无限重试。</span></div>;
  if (!outcome) return <EmptyState>选择一个经营场景，或输入你的业务问题</EmptyState>;
  if (isAnalysisResult(outcome)) {
    if (outcome.rows.length === 0) return <div className="result-message success"><strong>查询成功</strong><p>查询成功，但没有符合当前筛选条件的数据</p></div>;
    return <div className={`result-message ${outcome.status === "degraded" ? "warning" : "success"}`}><p>{localizeAnswer(outcome.answer)}</p>{outcome.degradation_reason && <span>本次查询的总结生成失败，已保留结果表格。详见审计依据。</span>}</div>;
  }
  if (outcome.status === "pending") return <div className="result-message warning"><strong>高风险查询，需管理员审批</strong><p>访问数据库前已暂停，尚未读取敏感数据。</p></div>;
  if (outcome.status === "rejected") return <div className="result-message danger"><strong>本次请求在数据库执行前被拒绝</strong><p>{outcome.reason ? localizeUserMessage(outcome.reason) : "请求不符合当前业务与安全边界。"}</p></div>;
  return <div className="result-message neutral"><p>{"answer" in outcome ? localizeAnswer(outcome.answer) : "请求已处理。"}</p></div>;
}

function ResultTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) return <EmptyState>运行分析后，这里显示结构化结果表格</EmptyState>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="table-scroll">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{label(column)}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td className={isNumeric(row[column]) ? "numeric mono" : ""} key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function EvidenceColumn({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <div className="evidence-column"><div className="evidence-title">{icon}<h3>{title}</h3></div>{children}</div>;
}

function PlanView({ result }: { result: AnalysisResult }) {
  const plan = result.plan;
  if (!plan) return null;
  return <dl className="plan-list"><div><dt>指标</dt><dd>{plan.metrics.map(label).join("、")}</dd></div><div><dt>维度</dt><dd>{plan.dimensions.map(label).join("、") || "不分组"}</dd></div><div><dt>时间</dt><dd>{plan.time_range ? `最近 ${plan.time_range.days} 天` : "未指定"}</dd></div><div><dt>返回</dt><dd className="mono">最多 {plan.limit} 条</dd></div></dl>;
}

function ApprovalDrawer({ approval, onClose, onResolve }: { approval: ApprovalRequired; onClose: () => void; onResolve: (decision: "approve" | "reject", reason?: string) => void }) {
  const [reason, setReason] = useState("");
  return <Drawer title="高风险查询 · 等待审批" subtitle={`请求编号 ${approval.request_id}`} onClose={onClose}><div className="approval-warning"><span className="service-dot warning" />尚未访问数据库 · 等待管理员批准后才能继续执行</div><dl className="approval-summary"><div><dt>申请角色</dt><dd>{approval.access_role === "admin" ? "管理员" : "分析员"}</dd></div><div><dt>预计行数</dt><dd className="mono">{approval.result_limit} 行</dd></div></dl><span className="field-label">SQL 只读预览 · 指纹 {approval.sql_fingerprint.slice(0, 8)}…{approval.sql_fingerprint.slice(-4)}</span><pre className="sql-block">{approval.sql}</pre><div className="sensitive-fields"><span>触发审批</span>{approval.sensitive_columns.map((field) => <StatusPill status="danger" key={field}>{field}</StatusPill>)}</div><label htmlFor="rejectReason">拒绝原因（拒绝时必填）</label><textarea id="rejectReason" rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：超出当前数据权限范围" /><div className="drawer-actions"><button className="danger-button" type="button" disabled={!reason.trim()} onClick={() => onResolve("reject", reason.trim())}>拒绝</button><button className="primary-button" type="button" onClick={() => onResolve("approve")}><Check size={16} />批准并执行</button></div></Drawer>;
}

function TraceDrawer({ requestId, events, error, onClose }: { requestId: string; events: TraceEvent[]; error: string; onClose: () => void }) {
  return <Drawer title="执行记录" subtitle={`请求编号 ${requestId}`} onClose={onClose}><p className="drawer-note">仅展示节点状态、耗时与尝试次数，不展示模型隐式思考或内部堆栈。</p>{error ? <div className="result-message danger">{error}</div> : events.length === 0 ? <EmptyState>当前请求还没有可查看的系统运行记录</EmptyState> : <div className="table-scroll"><table><thead><tr><th>节点</th><th>时间</th><th>耗时</th><th>状态</th><th>尝试</th></tr></thead><tbody>{events.map((event, index) => <tr key={`${event.component}-${index}`}><td>{traceComponentLabels[event.component] ?? event.component}</td><td className="mono">{new Date(event.occurred_at).toLocaleTimeString("zh-CN", { hour12: false })}</td><td className="mono numeric">{event.duration_ms === null || event.duration_ms === undefined ? "—" : `${event.duration_ms} ms`}</td><td><StatusPill status={outcomeVisualStatus(event.status)}>{traceStatusLabel(event.status)}</StatusPill></td><td className="mono numeric">{event.attempt}</td></tr>)}</tbody></table></div>}</Drawer>;
}

function traceStatusLabel(status: string) {
  return ({ started: "开始", succeeded: "成功", failed: "失败", retry_scheduled: "等待重试", rejected: "拒绝", pending: "等待审批", degraded: "降级" } as Record<string, string>)[status] ?? status;
}

function makeRequestId() {
  const date = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  let suffix: string;
  if (typeof globalThis.crypto?.randomUUID === "function") {
    suffix = globalThis.crypto.randomUUID().slice(0, 8).toUpperCase();
  } else {
    const bytes = new Uint8Array(4);
    if (typeof globalThis.crypto?.getRandomValues === "function") {
      globalThis.crypto.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    suffix = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase();
  }

  return `REQ-${date}-${suffix}`;
}

function AgentPanel({ response, running }: { response: AgentResponse | null; running: boolean }) {
  const plan = response?.task_plan;
  const report = response?.report;
  return (
    <section className="agent-card" aria-labelledby="agent-heading">
      <div className="section-title-row">
        <div>
          <h2 id="agent-heading">Agent 执行面板</h2>
          <p>{running ? "正在按计划收集数据与制度证据" : "保留可解释的任务边界、工具调用和证据链"}</p>
        </div>
        {response && <StatusPill status={response.status === "succeeded" ? "success" : response.status === "degraded" ? "warning" : "danger"}>{agentStatusLabel(response.status)}</StatusPill>}
      </div>
      {!response ? <EmptyState>提交一个复盘问题后，这里会显示 Agent 的执行状态</EmptyState> : (
        <>
          <div className="agent-summary-grid">
            <div><span>Skill</span><strong>{skillLabel(response.skill_id)}</strong></div>
            <div><span>上下文</span><strong className="mono">{response.context?.token_estimate ?? 0} / {response.context?.token_budget ?? 0} tokens</strong></div>
            <div><span>工具调用</span><strong className="mono">{response.tool_calls.length} 次</strong></div>
            <div><span>证据</span><strong className="mono">{(report?.data_evidence.length ?? 0) + (report?.document_evidence.length ?? 0)} 条</strong></div>
          </div>
          {plan && <div className="agent-section"><div className="agent-section-title"><ListChecks size={15} />任务计划</div><ol className="agent-task-list">{plan.subtasks.map((task) => <li key={task.id}><span className={`task-dot ${task.status}`} /> <span>{task.description}</span><code>{task.required_tools.join(" · ")}</code></li>)}</ol></div>}
          <div className="agent-columns">
            <div className="agent-section"><div className="agent-section-title"><Clock3 size={15} />工具时间线</div><ul className="agent-tool-list">{response.tool_calls.map((call, index) => <li key={`${call.tool_name}-${index}`}><strong>{call.tool_name}</strong><span>{call.status}</span><code>{call.duration_ms} ms</code></li>)}</ul></div>
            <div className="agent-section"><div className="agent-section-title"><FileSearch size={15} />证据账本</div><ul className="plain-list">{(report?.data_evidence ?? []).map((item) => <li key={item}>数据 · {item}</li>)}{(report?.document_evidence ?? []).map((item) => <li key={item}>制度 · {item}</li>)}{!report?.data_evidence.length && !report?.document_evidence.length && <li>当前没有可引用证据</li>}</ul></div>
          </div>
          {report && <div className={`agent-report ${response.status === "degraded" ? "warning" : ""}`}><div className="agent-section-title"><FileOutput size={15} />复盘报告</div><p>{report.executive_summary}</p><ul className="plain-list">{report.findings.map((finding, index) => <li key={`${finding.statement}-${index}`}>{finding.statement}</li>)}</ul>{response.exported_report && <details><summary>查看 Markdown 导出</summary><pre>{response.exported_report}</pre></details>}</div>}
          {response.limitations.length > 0 && <div className="agent-limitations"><ShieldAlert size={15} /><span>{response.limitations.join("；")}</span></div>}
        </>
      )}
    </section>
  );
}

function skillLabel(skill?: AgentResponse["skill_id"] | null) {
  return ({ refund_diagnosis: "退款异常诊断", channel_comparison: "渠道对比", product_analysis: "商品分析", weekly_report: "经营周报" } as Record<string, string>)[skill ?? ""] ?? "等待路由";
}

function agentStatusLabel(status: AgentResponse["status"]) {
  return ({ succeeded: "已完成", degraded: "部分完成", pending: "等待审批", refused: "已拒绝", failed: "失败", running: "执行中" } as Record<string, string>)[status] ?? status;
}

function clampRows(value: number, maximum: number) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(maximum, Math.max(1, Math.trunc(value)));
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

function isAnalysisResult(outcome: AnalysisOutcome | null): outcome is AnalysisResult {
  return outcome !== null && (outcome.status === "succeeded" || outcome.status === "degraded");
}

function isNumeric(value: unknown) {
  return typeof value === "number" || (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value));
}

import { BookOpenText, Filter, RefreshCw, Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import { EmptyState, LoadingBlock, StatusPill, outcomeVisualStatus } from "./components";
import { label } from "./localization";
import type { AuditEntry, MetricDefinition } from "./types";

const auditStatusLabels: Record<string, string> = {
  running: "进行中",
  succeeded: "成功",
  approval_required: "等待审批",
  rejected: "已拒绝",
  degraded: "降级",
  failed: "执行失败",
};

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState("");
  const [userId, setUserId] = useState("");
  const [status, setStatus] = useState("");
  const [approval, setApproval] = useState("");
  const [days, setDays] = useState("30");

  async function load() {
    setEntries(null);
    setError("");
    const query = new URLSearchParams({ days, limit: "100" });
    if (requestId.trim()) query.set("request_id", requestId.trim());
    if (userId.trim()) query.set("user_id", userId.trim());
    if (status) query.set("status", status);
    if (approval) query.set("approval_required", approval);
    try {
      setEntries(await api.audit(query.toString()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审计记录读取失败。");
      setEntries([]);
    }
  }

  useEffect(() => { void load(); }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    void load();
  }

  return (
    <main className="admin-page">
      <div className="page-heading">
        <div><h1>审计记录</h1><p>管理员可查看授权范围内的请求记录，用于合规检查与业务追责。</p></div>
        <button className="secondary-button" type="button" onClick={() => void load()}><RefreshCw size={15} />刷新</button>
      </div>
      <form className="filter-bar" onSubmit={submit}>
        <label>请求编号<input value={requestId} onChange={(event) => setRequestId(event.target.value)} placeholder="全部" /></label>
        <label>用户<input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="全部" /></label>
        <label>时间范围<select value={days} onChange={(event) => setDays(event.target.value)}><option value="7">近7天</option><option value="30">近30天</option><option value="90">近90天</option><option value="365">近一年</option></select></label>
        <label>审计状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部</option>{Object.entries(auditStatusLabels).map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></label>
        <label>是否触发审批<select value={approval} onChange={(event) => setApproval(event.target.value)}><option value="">全部</option><option value="true">是</option><option value="false">否</option></select></label>
        <button className="primary-button filter-submit" type="submit"><Search size={15} />查询</button>
      </form>

      <section className="admin-table-card">
        {entries === null ? <LoadingBlock text="正在读取审计记录" /> : error ? <div className="result-message danger">{error}</div> : entries.length === 0 ? <EmptyState>当前筛选条件下没有审计记录</EmptyState> : (
          <div className="table-scroll"><table><thead><tr><th>请求时间</th><th>用户</th><th>原始问题摘要</th><th>状态</th><th>行数</th><th>耗时</th><th>审批</th><th>请求编号</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.request_id}><td className="mono">{formatDate(entry.created_at)}</td><td>{entry.user_id}</td><td className="question-cell">{entry.original_question}</td><td><StatusPill status={outcomeVisualStatus(entry.status)}>{auditStatusLabels[entry.status]}</StatusPill></td><td className="mono numeric">{entry.row_count ?? "—"}</td><td className="mono numeric">{entry.duration_ms === null || entry.duration_ms === undefined ? "—" : `${Math.round(entry.duration_ms)} ms`}</td><td>{entry.approval_required ? <StatusPill status="warning">已触发</StatusPill> : "否"}</td><td><code>{entry.request_id}</code></td></tr>)}</tbody></table></div>
        )}
      </section>
    </main>
  );
}

export function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricDefinition[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.metrics().then(setMetrics).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "指标口径读取失败。");
      setMetrics([]);
    });
  }, []);

  return (
    <main className="admin-page">
      <div className="page-heading">
        <div><h1>指标与业务口径</h1><p>只读 · 展示模型生成查询时使用的真实版本、公式、数据来源与固定规则。</p></div>
        <StatusPill status="neutral">只读</StatusPill>
      </div>
      <section className="metric-overview">
        <BookOpenText size={18} />
        <div><strong>版本化指标字典</strong><p>指标定义由代码和测试维护，前端不会修改公式或固定业务规则。</p></div>
      </section>
      <section className="admin-table-card">
        {metrics === null ? <LoadingBlock text="正在读取指标口径" /> : error ? <div className="result-message danger">{error}</div> : metrics.length === 0 ? <EmptyState>当前没有可展示的指标口径</EmptyState> : (
          <div className="table-scroll"><table className="metrics-table"><thead><tr><th>指标名称</th><th>业务定义</th><th>公式</th><th>固定规则</th><th>来源表</th><th>支持维度</th><th>版本</th></tr></thead><tbody>{metrics.map((metric) => <tr key={metric.source_id}><td><strong>{metric.name}</strong><code>{metric.source_id}</code></td><td>{metric.description}</td><td><code className="formula">{metric.formula}</code></td><td>{metric.fixed_rules.length ? metric.fixed_rules.map(localizeRule).join("；") : "无固定筛选"}</td><td><code>{metric.source_tables.join(" + ")}</code></td><td>{metric.supported_dimensions.map(label).join("、") || "不支持分组"}</td><td><StatusPill status="success">{metric.version}</StatusPill></td></tr>)}</tbody></table></div>
        )}
      </section>
    </main>
  );
}

function localizeRule(rule: string) {
  return rule.replace("order_status equals paid", "订单状态 = 已支付");
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

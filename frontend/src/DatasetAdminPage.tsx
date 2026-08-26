import {
  AlertTriangle,
  Archive,
  Check,
  Database,
  FileUp,
  Play,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import {
  Drawer,
  EmptyState,
  LoadingBlock,
  StatusPill,
} from "./components";
import type {
  DatasetMetric,
  DatasetProfile,
  DatasetRecord,
  MetricProposals,
} from "./types";

const datasetStatusLabels: Record<string, string> = {
  uploaded: "已上传",
  profiling: "分析中",
  needs_mapping: "待确认映射",
  ready: "可查询",
  failed: "分析失败",
  archived: "已归档",
};

const datasetStatusVisual: Record<string, "neutral" | "running" | "warning" | "success" | "danger"> = {
  uploaded: "neutral",
  profiling: "running",
  needs_mapping: "warning",
  ready: "success",
  failed: "danger",
  archived: "neutral",
};

const roleLabels: Record<string, string> = {
  order_id: "订单号",
  product_id: "商品",
  amount: "金额",
  quantity: "数量",
  channel: "渠道",
  category: "品类",
  region: "地区",
  status: "状态",
  time: "时间",
};

export default function DatasetAdminPage() {
  const [records, setRecords] = useState<DatasetRecord[] | null>(null);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState<{ kind: "success" | "danger"; text: string } | null>(null);
  const [selected, setSelected] = useState<DatasetRecord | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [proposals, setProposals] = useState<MetricProposals | null>(null);
  const [detailError, setDetailError] = useState("");
  const [busy, setBusy] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [sourceType, setSourceType] = useState<"csv" | "parquet">("csv");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  async function load() {
    setRecords(null);
    setError("");
    try {
      setRecords(await api.adminDatasets());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据集列表读取失败。");
      setRecords([]);
    }
  }

  useEffect(() => { void load(); }, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    const id = datasetId.trim();
    const name = datasetName.trim();
    if (!id || !name || !file) return;
    setUploading(true);
    setActionMessage(null);
    setError("");
    try {
      const form = new FormData();
      form.set("dataset_id", id);
      form.set("dataset_name", name);
      form.set("version", "1");
      form.set("source_type", sourceType);
      form.set("file", file);
      await api.adminUpload(form);
      setDatasetId("");
      setDatasetName("");
      setFile(null);
      setActionMessage({ kind: "success", text: `数据集 ${id} 已上传。选中后点击「开始分析」进行数据画像。` });
      await load();
    } catch (reason) {
      setActionMessage({ kind: "danger", text: reason instanceof Error ? reason.message : "上传失败。" });
    } finally {
      setUploading(false);
    }
  }

  async function openDetail(record: DatasetRecord) {
    setSelected(record);
    setProfile(null);
    setProposals(null);
    setDetailError("");
    setActionMessage(null);
    if (record.status === "uploaded" || record.status === "profiling") return;
    await fetchDetail(record);
  }

  async function fetchDetail(record: DatasetRecord) {
    setBusy(true);
    setDetailError("");
    try {
      const detail = await api.adminDatasetProfile(record.dataset_id, record.version);
      setProfile(detail);
      setSelected(detail.dataset);
      if (detail.dataset.mapping_confirmed) {
        try {
          setProposals(await api.adminMetricProposals(record.dataset_id, record.version));
        } catch {
          setProposals(null);
        }
      }
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "数据集详情读取失败。");
    } finally {
      setBusy(false);
    }
  }

  async function runAnalysis() {
    if (!selected) return;
    await fetchDetail(selected);
    await load();
  }

  async function confirmMapping() {
    if (!selected || !profile) return;
    setBusy(true);
    setDetailError("");
    try {
      const updated = await api.adminConfirmMapping(selected.dataset_id, selected.version, profile.mapping);
      setSelected(updated);
      setProfile((current) => current ? {
        ...current,
        dataset: updated,
        mapping: { ...current.mapping, confirmed: true },
      } : current);
      setActionMessage({ kind: "success", text: "字段映射已确认，可生成指标建议。" });
      await load();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "映射确认失败。");
    } finally {
      setBusy(false);
    }
  }

  async function loadProposals() {
    if (!selected) return;
    setBusy(true);
    setDetailError("");
    try {
      setProposals(await api.adminMetricProposals(selected.dataset_id, selected.version));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "指标建议生成失败。");
    } finally {
      setBusy(false);
    }
  }

  async function confirmMetric(metric: DatasetMetric) {
    if (!selected) return;
    setBusy(true);
    setDetailError("");
    try {
      await api.adminConfirmMetric(selected.dataset_id, selected.version, metric.metric_id);
      setProposals(await api.adminMetricProposals(selected.dataset_id, selected.version));
      setActionMessage({ kind: "success", text: `指标「${metric.name}」已确认。` });
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "指标确认失败。");
    } finally {
      setBusy(false);
    }
  }

  async function markReady() {
    if (!selected) return;
    setBusy(true);
    setDetailError("");
    try {
      const updated = await api.adminMarkReady(selected.dataset_id, selected.version);
      setSelected(updated);
      setProfile((current) => current ? { ...current, dataset: updated } : current);
      setActionMessage({ kind: "success", text: "数据集已标记为可用，分析员现在可以选择并查询。" });
      await load();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "标记为可用失败。");
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!selected) return;
    if (!window.confirm("归档后该数据集将不再对分析员可见，确认归档？")) return;
    setBusy(true);
    setDetailError("");
    try {
      await api.adminArchive(selected.dataset_id, selected.version);
      setSelected(null);
      setProfile(null);
      setProposals(null);
      setActionMessage({ kind: "success", text: "数据集已归档。" });
      await load();
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "归档失败。");
    } finally {
      setBusy(false);
    }
  }

  const canConfirmMapping = profile !== null && !profile.dataset.mapping_confirmed && profile.mapping.fields.length > 0;
  const canGenerateMetrics = profile !== null && profile.dataset.mapping_confirmed;
  const hasConfirmedMetrics = proposals?.metrics.some((metric) => metric.status === "confirmed") ?? false;
  const canMarkReady = selected?.status === "needs_mapping" && hasConfirmedMetrics;

  return (
    <main className="admin-page">
      <div className="page-heading">
        <div><h1>数据集管理</h1><p>上传数据文件，完成画像、字段映射与指标确认，使数据可被分析员查询引用。</p></div>
        <button className="secondary-button" type="button" onClick={() => void load()}><RefreshCw size={15} />刷新</button>
      </div>

      {actionMessage && <div className={`result-message ${actionMessage.kind}`}>{actionMessage.text}</div>}

      <section className="dataset-upload-card">
        <form className="dataset-upload-form" onSubmit={upload}>
          <div className="dataset-upload-heading"><FileUp size={16} /><strong>上传数据文件</strong><small>CSV 或 Parquet 单文件；系统将自动建立暂存表并生成数据画像。</small></div>
          <div className="dataset-upload-grid">
            <label>数据集编号<input value={datasetId} onChange={(event) => setDatasetId(event.target.value)} placeholder="例如 sales_2026" maxLength={60} /></label>
            <label>数据集名称<input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="例如 2026年销售明细" maxLength={200} /></label>
            <label>文件格式<select value={sourceType} onChange={(event) => setSourceType(event.target.value as "csv" | "parquet")}><option value="csv">CSV</option><option value="parquet">Parquet</option></select></label>
            <label className="dataset-file-field">数据文件<input className="dataset-file-input" type="file" accept=".csv,.parquet" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><span className="dataset-file-name">{file ? file.name : "选择文件"}</span></label>
          </div>
          <button className="primary-button" type="submit" disabled={uploading || !datasetId.trim() || !datasetName.trim() || !file}>
            {uploading ? "上传中…" : "上传数据集"}
          </button>
        </form>
      </section>

      <section className="admin-table-card">
        {records === null ? <LoadingBlock text="正在读取数据集列表" /> : error ? <div className="result-message danger">{error}</div> : records.length === 0 ? <EmptyState>还没有数据集，请先上传数据文件</EmptyState> : (
          <div className="table-scroll"><table><thead><tr><th>数据集</th><th>版本</th><th>格式</th><th>状态</th><th>行数</th><th>字段映射</th><th>更新时间</th><th /></tr></thead><tbody>{records.map((record) => <tr key={`${record.dataset_id}-${record.version}`} className={selected?.dataset_id === record.dataset_id && selected.version === record.version ? "row-active" : ""}><td><strong>{record.dataset_name}</strong><code>{record.dataset_id}</code></td><td className="mono">v{record.version}</td><td>{record.source_type === "parquet" ? "Parquet" : "CSV"}</td><td><StatusPill status={datasetStatusVisual[record.status]}>{datasetStatusLabels[record.status]}</StatusPill></td><td className="mono numeric">{record.row_count.toLocaleString()}</td><td>{record.mapping_confirmed ? <StatusPill status="success">已确认</StatusPill> : <StatusPill status="neutral">未确认</StatusPill>}</td><td className="mono">{record.updated_at ? formatDate(record.updated_at) : "—"}</td><td><button className="row-action" type="button" onClick={() => void openDetail(record)}>{record.status === "uploaded" ? "开始分析" : record.status === "ready" ? "查看" : "处理"}</button></td></tr>)}</tbody></table></div>
        )}
      </section>

      {selected && (
        <Drawer
          title="数据集 onboarding"
          subtitle={`${selected.dataset_id} · v${selected.version} · ${selected.dataset_name}`}
          width="wide"
          onClose={() => setSelected(null)}
        >
          {busy ? <LoadingBlock text="正在处理数据集" /> : detailError ? <div className="result-message danger">{detailError}<button className="inline-retry" type="button" onClick={() => void fetchDetail(selected)}>重试</button></div> : profile === null ? (
            selected.status === "uploaded" ? (
              <div className="dataset-detail-empty">
                <Database size={22} />
                <p>该数据集已上传，尚未进行数据画像。</p>
                <button className="primary-button" type="button" onClick={() => void runAnalysis()}><Play size={15} />开始分析</button>
              </div>
            ) : selected.status === "profiling" ? (
              <div className="dataset-detail-empty"><LoadingBlock text="数据集正在分析中，请刷新列表" /><button className="secondary-button" type="button" onClick={() => void load()}>刷新</button></div>
            ) : (
              <div className="dataset-detail-empty"><p>无法读取数据集详情。</p></div>
            )
          ) : (
            <DatasetDetail
              profile={profile}
              proposals={proposals}
              busy={busy}
              canConfirmMapping={canConfirmMapping}
              canGenerateMetrics={canGenerateMetrics}
              hasConfirmedMetrics={hasConfirmedMetrics}
              canMarkReady={canMarkReady}
              onConfirmMapping={() => void confirmMapping()}
              onGenerateMetrics={() => void loadProposals()}
              onConfirmMetric={(metric) => void confirmMetric(metric)}
              onMarkReady={() => void markReady()}
              onArchive={() => void archive()}
              onRetryAnalysis={() => void runAnalysis()}
            />
          )}
        </Drawer>
      )}
    </main>
  );
}

function DatasetDetail({
  profile,
  proposals,
  busy,
  canConfirmMapping,
  canGenerateMetrics,
  hasConfirmedMetrics,
  canMarkReady,
  onConfirmMapping,
  onGenerateMetrics,
  onConfirmMetric,
  onMarkReady,
  onArchive,
  onRetryAnalysis,
}: {
  profile: DatasetProfile;
  proposals: MetricProposals | null;
  busy: boolean;
  canConfirmMapping: boolean;
  canGenerateMetrics: boolean;
  hasConfirmedMetrics: boolean;
  canMarkReady: boolean;
  onConfirmMapping: () => void;
  onGenerateMetrics: () => void;
  onConfirmMetric: (metric: DatasetMetric) => void;
  onMarkReady: () => void;
  onArchive: () => void;
  onRetryAnalysis: () => void;
}) {
  const record = profile.dataset;
  const issues = profile.quality.issues;
  return (
    <div className="dataset-detail">
      <div className="dataset-detail-header">
        <div className="onboarding-steps">
          <OnboardingStep done active label="数据画像" />
          <OnboardingStep done={record.mapping_confirmed} active={!record.mapping_confirmed && record.status !== "ready"} label="字段映射" />
          <OnboardingStep done={hasConfirmedMetrics} active={record.status === "needs_mapping"} label="指标确认" />
          <OnboardingStep done={record.status === "ready"} active={record.status === "ready"} label="可查询" />
        </div>
        <div className="dataset-detail-actions">
          {record.status === "failed" && <button className="secondary-button" type="button" onClick={onRetryAnalysis}><Play size={15} />重新分析</button>}
          {record.status === "needs_mapping" && canConfirmMapping && <button className="primary-button" type="button" onClick={onConfirmMapping} disabled={busy}><Check size={15} />确认字段映射</button>}
          {record.status === "needs_mapping" && canGenerateMetrics && !hasConfirmedMetrics && <button className="primary-button" type="button" onClick={onGenerateMetrics} disabled={busy}><Sparkles size={15} />生成指标建议</button>}
          {record.status === "needs_mapping" && canMarkReady && <button className="primary-button" type="button" onClick={onMarkReady} disabled={busy}><Check size={15} />标记为可用</button>}
          {record.status === "ready" && <button className="danger-button" type="button" onClick={onArchive} disabled={busy}><Archive size={15} />归档</button>}
        </div>
      </div>

      {record.status === "failed" && (
        <section className="dataset-quality danger">
          <AlertTriangle size={16} />
          <div><strong>数据质量检查未通过</strong><p>该数据集暂不能标记为可用，请检查以下问题并重新上传或调整数据。</p></div>
        </section>
      )}

      <section className="dataset-section">
        <h3>数据画像</h3>
        <div className="dataset-facts">
          <div><span>暂存模式</span><code>{profile.import_result.schema_name}</code></div>
          <div><span>数据表</span><strong>{profile.import_result.tables.length}</strong></div>
          <div><span>总行数</span><strong className="mono">{profile.import_result.row_counts && Object.values(profile.import_result.row_counts).reduce((sum, count) => sum + count, 0).toLocaleString()}</strong></div>
          <div><span>质量检查行</span><strong className="mono">{profile.quality.checked_rows.toLocaleString()}</strong></div>
        </div>
        {profile.schema.tables.map((table) => (
          <div className="schema-table-card" key={table.table_name}>
            <div className="schema-table-heading"><code>{table.table_name}</code><span className="mono">{table.row_count.toLocaleString()} 行</span></div>
            <div className="table-scroll"><table className="schema-columns-table"><thead><tr><th>列名</th><th>类型</th><th>空值率</th><th>唯一率</th><th>候选角色</th><th>示例值</th></tr></thead><tbody>{table.columns.map((column) => (
              <tr key={column.name}><td><code>{column.name}</code></td><td>{column.normalized_type}</td><td className="mono">{(column.null_ratio * 100).toFixed(0)}%</td><td className="mono">{(column.unique_ratio * 100).toFixed(0)}%</td><td>{column.candidate_roles.length ? column.candidate_roles.map((role) => <span className="role-chip" key={role}>{roleLabels[role] ?? role}</span>) : "—"}</td><td className="sample-values">{column.sample_values.length ? column.sample_values.slice(0, 3).map((value, index) => <code key={index}>{String(value)}</code>) : "—"}</td></tr>))}</tbody></table></div>
          </div>
        ))}
      </section>

      {issues.length > 0 && (
        <section className="dataset-section">
          <h3>质量报告</h3>
          <ul className="quality-issue-list">
            {issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>
                {issue.severity === "critical" ? <StatusPill status="danger">严重</StatusPill> : issue.severity === "warning" ? <StatusPill status="warning">警告</StatusPill> : <StatusPill status="neutral">提示</StatusPill>}
                <div><strong>{issue.message}</strong><small>{issue.table}{issue.column ? ` · ${issue.column}` : ""} · <code>{issue.code}</code></small></div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="dataset-section">
        <h3>字段映射 {record.mapping_confirmed && <StatusPill status="success">已确认</StatusPill>}</h3>
        {profile.mapping.fields.length === 0 ? <p className="dataset-section-muted">尚未生成字段映射，请先完成数据画像。</p> : (
          <div className="mapping-grid">
            {profile.mapping.fields.map((field) => (
              <div className="mapping-card" key={field.role}>
                <StatusPill status="neutral">{roleLabels[field.role] ?? field.role}</StatusPill>
                <div><code>{field.table}.{field.column}</code><small>置信度 {(field.confidence * 100).toFixed(0)}%{field.reasons.length ? ` · ${field.reasons[0]}` : ""}</small></div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="dataset-section">
        <div className="dataset-section-heading"><h3>指标口径</h3>{proposals === null && canGenerateMetrics && !hasConfirmedMetrics && <button className="secondary-button" type="button" onClick={onGenerateMetrics} disabled={busy}><Sparkles size={15} />生成建议</button>}</div>
        {proposals === null ? (
          <p className="dataset-section-muted">{record.mapping_confirmed ? "点击「生成指标建议」为已确认字段推导指标。" : "确认字段映射后即可基于语义角色推导指标定义。"}</p>
        ) : proposals.metrics.length === 0 ? (
          <EmptyState>没有可生成的指标，请检查字段映射是否完整</EmptyState>
        ) : (
          <div className="metric-catalog">
            {proposals.metrics.map((metric) => (
              <div className="metric-card" key={metric.metric_id}>
                <div className="metric-card-main">
                  <strong>{metric.name}</strong><code>{metric.metric_id}</code>
                  <p>{metric.definition}</p>
                </div>
                <div className="metric-card-formula"><span>公式</span><code>{metric.formula}</code><small>来源 {metric.source_table}.{metric.source_column}</small></div>
                <div className="metric-card-side">
                  {metric.status === "confirmed" ? <StatusPill status="success">已确认</StatusPill> : <button className="secondary-button" type="button" onClick={() => onConfirmMetric(metric)} disabled={busy}><Check size={14} />确认</button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function OnboardingStep({ done, active, label }: { done: boolean; active: boolean; label: string }) {
  return (
    <div className={`onboarding-step ${done ? "done" : ""} ${active ? "active" : ""}`}>
      <span>{done ? <Check size={12} /> : null}</span>
      <small>{label}</small>
    </div>
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

import {
  BookOpenCheck,
  Database,
  FileSearch,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { lazy, Suspense } from "react";
import type { AssistantView } from "../chatModels";
import { EmptyState, StatusPill } from "../components";
import { localizeAnswer } from "../localization";
import type { AnalysisOutcome, AnalysisResult, ResultDisplayMode } from "../types";
import AgentProgress from "./AgentProgress";
import ResultTable from "./ResultTable";
import { BrandMark, BRAND } from "../brand";

const ResultChart = lazy(() => import("../ResultChart"));

export default function AssistantResponse({
  view,
  onOpenSources,
  onOpenExecution,
  onOpenAudit,
  onFollowUp,
  onRetry,
  onOpenApproval,
  resultDisplay = "auto",
}: {
  view: AssistantView;
  onOpenSources: () => void;
  onOpenExecution: () => void;
  onOpenAudit: () => void;
  onFollowUp: (result: AnalysisResult) => void;
  onRetry: () => void;
  onOpenApproval?: () => void;
  resultDisplay?: ResultDisplayMode;
}) {
  const response = view.response;
  const outcome = response?.analysis ?? view.outcome;
  const analysis = isAnalysisResult(outcome) ? outcome : null;
  const answer = response?.answer || analysis?.answer || outcomeAnswer(outcome) || view.fallbackAnswer;
  const knowledgeCount = response?.knowledge_evidence?.length ?? 0;
  const dataCount = response?.report?.data_evidence.length ?? analysis?.evidence_source_ids.length ?? 0;
  const limitations = response?.limitations ?? [];
  const showChart = Boolean(analysis?.chart_spec) && resultDisplay !== "table";
  const showTable = Boolean(analysis?.rows.length)
    && (resultDisplay !== "auto" || !analysis?.chart_spec);

  return (
    <article className="assistant-message" aria-label="知枢 AI 回答">
      <div className="assistant-identity"><BrandMark decorative className="assistant-mark" /><div><strong>{BRAND.assistantName}</strong><small>{modeLabel(response?.agent_mode)}</small></div></div>
      <div className="assistant-content">
        <AgentProgress view={view} onOpen={onOpenExecution} />

        {view.running && !answer && (
          <div className="answer-loading" role="status">
            <span /><span /><span />
          </div>
        )}

        {view.failure && (
          <div className="answer-state danger">
            <strong>本次请求未能完成</strong>
            <p>{view.failure}</p>
            <button type="button" onClick={onRetry}><RefreshCw size={15} />重新执行</button>
          </div>
        )}

        {!view.failure && (view.status === "pending" || outcome?.status === "pending") && (
          <div className="answer-state warning"><strong>高风险查询正在等待审批</strong><p>数据库尚未执行，管理员批准后会从当前节点继续。</p>{onOpenApproval && <button type="button" onClick={onOpenApproval}>查看审批</button>}</div>
        )}

        {!view.failure && outcome?.status === "rejected" && (
          <div className="answer-state danger"><strong>请求已被拒绝</strong><p>{outcome.reason || "当前请求不符合业务或权限边界。"}</p></div>
        )}

        {answer && <div className="answer-prose"><p>{localizeAnswer(answer)}</p></div>}

        {limitations.length > 0 && (
          <div className="answer-limitations"><strong>当前边界</strong><p>{limitations.join("；")}</p></div>
        )}

        {analysis && (showChart || showTable) && (
          <section className="inline-analysis" aria-label="分析结果">
            <div className="inline-analysis-heading">
              <div><Database size={16} /><span>{analysis.plan?.analysis_goal ? localizeAnswer(analysis.plan.analysis_goal) : "受控数据查询"}</span></div>
              <StatusPill status={analysis.status === "degraded" ? "warning" : "success"}>{analysis.status === "degraded" ? "结果降级" : "数据已验证"}</StatusPill>
            </div>
            {showChart && analysis.chart_spec && (
              <div className="inline-chart-panel">
                <Suspense fallback={<EmptyState>正在准备图表</EmptyState>}>
                  <ResultChart spec={analysis.chart_spec} rows={analysis.rows} />
                </Suspense>
              </div>
            )}
            {showTable && <ResultTable rows={analysis.rows} />}
          </section>
        )}

        {response?.report && response.report.findings.length > 0 && (
          <section className="response-findings">
            <div><BookOpenCheck size={16} /><strong>{response.report.title}</strong></div>
            <ul>{response.report.findings.map((finding, index) => <li key={`${finding.statement}-${index}`}>{finding.statement}</li>)}</ul>
          </section>
        )}

        {!view.running && !view.failure && (
          <div className="response-actions">
            {(knowledgeCount > 0 || dataCount > 0) && <button type="button" onClick={onOpenSources}><FileSearch size={15} />查看依据 <span>{knowledgeCount + dataCount}</span></button>}
            <button type="button" onClick={onOpenExecution}><ShieldCheck size={15} />执行过程</button>
            <button type="button" onClick={onOpenAudit}>请求详情</button>
            {analysis?.plan && <button type="button" onClick={() => onFollowUp(analysis)}>基于结果追问</button>}
          </div>
        )}
      </div>
    </article>
  );
}

function outcomeAnswer(outcome: AnalysisOutcome | null): string {
  if (!outcome || outcome.status === "pending" || outcome.status === "rejected") return "";
  return outcome.answer;
}

function isAnalysisResult(outcome: AnalysisOutcome | null): outcome is AnalysisResult {
  return outcome !== null && (outcome.status === "succeeded" || outcome.status === "degraded");
}

function modeLabel(mode?: string | null) {
  return ({
    general: "通用对话",
    knowledge: "企业知识",
    data: "经营数据",
    collaboration: "知识与数据协作",
  } as Record<string, string>)[mode ?? ""] ?? "企业智能助理";
}

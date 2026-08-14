import { CheckCircle2, CircleEllipsis, TriangleAlert } from "lucide-react";
import type { AssistantView } from "../chatModels";

export default function AgentProgress({ view, onOpen }: { view: AssistantView; onOpen: () => void }) {
  const status = progressStatus(view);
  return (
    <button className={`agent-progress ${status.tone}`} type="button" onClick={onOpen}>
      {status.tone === "running" ? <CircleEllipsis size={16} /> : status.tone === "danger" ? <TriangleAlert size={16} /> : <CheckCircle2 size={16} />}
      <span><strong>{status.label}</strong><small>{view.running ? view.statusMessage : "查看 Agent、工具与耗时"}</small></span>
      <span className="agent-progress-action">查看过程</span>
    </button>
  );
}

function progressStatus(view: AssistantView) {
  if (view.running) return { tone: "running", label: view.statusMessage || "正在执行" };
  if (view.failure) return { tone: "danger", label: "任务未完成" };
  if (view.response?.status === "degraded") return { tone: "warning", label: "任务部分完成" };
  if (view.response?.status === "refused" || view.outcome?.status === "rejected") return { tone: "danger", label: "任务已拒绝" };
  if (view.status === "pending" || view.outcome?.status === "pending") return { tone: "warning", label: "等待管理员审批" };
  return { tone: "success", label: "任务已完成" };
}

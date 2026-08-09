import { MessageSquarePlus, Trash2 } from "lucide-react";
import { auditSummary, type Conversation, type ConversationTurn } from "./conversations";

export default function ConversationPanel({
  conversations,
  activeId,
  onCreate,
  onSelect,
  onDelete,
  onSelectTurn,
}: {
  conversations: Conversation[];
  activeId: string;
  onCreate: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSelectTurn: (turn: ConversationTurn) => void;
}) {
  const active = conversations.find((conversation) => conversation.id === activeId) ?? null;
  const summary = active ? auditSummary(active) : null;
  return (
    <section className="conversation-panel" aria-label="历史对话">
      <div className="conversation-heading">
        <div><h2>历史对话</h2><span>仅保存在此浏览器</span></div>
        <button className="icon-button" type="button" onClick={onCreate} title="新建对话" aria-label="新建对话">
          <MessageSquarePlus size={17} />
        </button>
      </div>
      <div className="conversation-list">
        {conversations.map((conversation) => (
          <div className={`conversation-item ${conversation.id === activeId ? "active" : ""}`} key={conversation.id}>
            <button type="button" onClick={() => onSelect(conversation.id)}>
              <strong>{conversation.title}</strong>
              <span>{conversation.turns.length} 轮 · {new Date(conversation.updatedAt).toLocaleDateString("zh-CN")}</span>
            </button>
            <button type="button" onClick={() => onDelete(conversation.id)} title="删除对话" aria-label={`删除对话 ${conversation.title}`}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
      {summary && (
        <div className="conversation-audit">
          <strong>会话审计摘要</strong>
          <div><span>请求 {summary.total}</span><span>完成 {summary.succeeded}</span><span>拒绝 {summary.rejected}</span><span>失败 {summary.failed}</span></div>
          <small>平均耗时 {(summary.averageDurationMs / 1000).toFixed(1)}s · 审批等待 {summary.pending}</small>
        </div>
      )}
      {active && active.turns.length > 0 && (
        <div className="turn-list" aria-label="当前对话记录">
          {active.turns.slice().reverse().map((turn) => (
            <button type="button" key={turn.id} onClick={() => onSelectTurn(turn)}>
              <span>{turn.question}</span><small>{turnStatus(turn.status)}</small>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function turnStatus(status: ConversationTurn["status"]) {
  return ({
    succeeded: "查询成功",
    degraded: "查询降级",
    answered: "助手答复",
    needs_clarification: "等待补充",
    pending: "等待审批",
    rejected: "已拒绝",
    failed: "执行失败",
  } as const)[status];
}

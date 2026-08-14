import {
  BookOpenText,
  ClipboardList,
  LogOut,
  MessageSquarePlus,
  PanelLeftClose,
  Trash2,
} from "lucide-react";
import { auditSummary, type Conversation } from "../conversations";
import { roleLabel, type Page } from "../components";
import type { SessionInfo } from "../types";
import type { ConversationSyncState } from "../useConversationSync";

export default function ConversationRail({
  session,
  online,
  syncState,
  conversations,
  activeId,
  open,
  onClose,
  onCreate,
  onSelect,
  onDelete,
  onPage,
  onLogout,
}: {
  session: SessionInfo;
  online: boolean;
  syncState: ConversationSyncState;
  conversations: Conversation[];
  activeId: string;
  open: boolean;
  onClose: () => void;
  onCreate: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onPage: (page: Page) => void;
  onLogout: () => void;
}) {
  const active = conversations.find((item) => item.id === activeId) ?? null;
  const summary = active ? auditSummary(active) : null;
  return (
    <>
      {open && <button className="rail-scrim" type="button" onClick={onClose} aria-label="关闭会话导航" />}
      <aside className={`conversation-rail ${open ? "open" : ""}`} aria-label="会话导航">
        <div className="rail-brand-row">
          <button className="rail-brand" type="button" onClick={() => onPage("workspace")}>
            <span className="logo-mark">析</span>
            <span><strong>企析</strong><small>企业专业智能助理</small></span>
          </button>
          <button className="rail-close" type="button" onClick={onClose} aria-label="关闭会话导航" title="关闭导航">
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button className="new-conversation-button" type="button" onClick={onCreate}>
          <MessageSquarePlus size={17} />
          新建对话
        </button>

        <div className="rail-section-heading"><span>最近对话</span><small>{syncLabel(syncState)}</small></div>
        <div className="rail-conversation-list">
          {conversations.map((conversation) => (
            <div className={`rail-conversation ${conversation.id === activeId ? "active" : ""}`} key={conversation.id}>
              <button type="button" onClick={(event) => { event.currentTarget.blur(); onSelect(conversation.id); onClose(); }}>
                <strong>{conversation.title}</strong>
                <span>{conversation.turns.length} 轮 · {new Date(conversation.updatedAt).toLocaleDateString("zh-CN")}</span>
              </button>
              <button type="button" onClick={() => onDelete(conversation.id)} aria-label={`删除对话 ${conversation.title}`} title="删除对话">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        {summary && summary.total > 0 && (
          <div className="rail-session-summary">
            <span>当前会话</span>
            <strong>{summary.total} 次请求</strong>
            <small>{summary.succeeded} 次完成 · 平均 {(summary.averageDurationMs / 1000).toFixed(1)}s</small>
          </div>
        )}

        <div className="rail-footer">
          {session.role === "admin" && (
            <>
              <button type="button" onClick={() => onPage("audit")}><ClipboardList size={16} />审计记录</button>
              <button type="button" onClick={() => onPage("metrics")}><BookOpenText size={16} />指标口径</button>
            </>
          )}
          <div className="rail-account">
            <div><span className={`service-dot ${online ? "online" : "offline"}`} /><span><strong>{roleLabel(session.role)}</strong><small>{online ? "服务在线" : "服务未就绪"}</small></span></div>
            <button type="button" onClick={onLogout} aria-label="退出登录" title="退出登录"><LogOut size={16} /></button>
          </div>
        </div>
      </aside>
    </>
  );
}

function syncLabel(state: ConversationSyncState) {
  if (state === "syncing") return "正在同步";
  if (state === "synced") return "已同步到账号";
  return "仅保存在本机";
}

import { useEffect, useLayoutEffect, useRef } from "react";
import { ArrowUpRight, Database, FileSearch, Globe2, Sparkles } from "lucide-react";
import { assistantFromLiveTurn, assistantFromTurn, type InspectorTab, type LiveTurn } from "../chatModels";
import type { Conversation } from "../conversations";
import type { AnalysisResult, ResultDisplayMode } from "../types";
import AssistantResponse from "./AssistantResponse";

export const suggestedQuestions = [
  { icon: <FileSearch size={17} />, label: "企业制度", question: "公司的差旅报销制度是什么？" },
  { icon: <Database size={17} />, label: "经营分析", question: "统计最近30天各销售渠道的销售额，按销售额从高到低排序。" },
  { icon: <Sparkles size={17} />, label: "协作复盘", question: "结合退款数据和售后制度，分析最近30天的售后风险。" },
  { icon: <Globe2 size={17} />, label: "通用工具", question: "现在北京时间几点？" },
];

export default function ChatThread({
  conversation,
  liveTurn,
  onAsk,
  onInspect,
  onFollowUp,
  onRetry,
  pendingApprovalRequestId,
  onOpenApproval,
  resultDisplay,
}: {
  conversation: Conversation;
  liveTurn: LiveTurn | null;
  onAsk: (question: string) => void;
  onInspect: (requestId: string, tab: InspectorTab) => void;
  onFollowUp: (result: AnalysisResult) => void;
  onRetry: (question: string) => void;
  pendingApprovalRequestId: string | null;
  onOpenApproval: () => void;
  resultDisplay: ResultDisplayMode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldStickRef = useRef(true);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    shouldStickRef.current = true;
    container.scrollTop = container.scrollHeight;
  }, [conversation.id]);

  useEffect(() => {
    if (!shouldStickRef.current) return;
    const container = containerRef.current;
    if (!container) return;
    const frame = window.requestAnimationFrame(() => {
      container.scrollTo({ top: container.scrollHeight, behavior: liveTurn ? "smooth" : "auto" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [conversation.turns, liveTurn]);

  function trackScroll() {
    const container = containerRef.current;
    if (!container) return;
    shouldStickRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  }

  return (
    <div className="chat-thread" ref={containerRef} onScroll={trackScroll} tabIndex={0} aria-label="对话内容">
      {conversation.turns.length === 0 && liveTurn === null ? (
        <section className="chat-empty-state">
          <span className="empty-brand-mark">析</span>
          <h1>今天想了解什么？</h1>
          <p>我可以查询企业知识、分析经营数据，也可以使用通用工具处理日常问题。</p>
          <div className="suggestion-list">
            {suggestedQuestions.map((item) => (
              <button type="button" key={item.label} onClick={() => onAsk(item.question)}>
                <span>{item.icon}</span>
                <span><strong>{item.label}</strong><small>{item.question}</small></span>
                <ArrowUpRight size={16} />
              </button>
            ))}
          </div>
        </section>
      ) : (
        <div className="message-list">
          {conversation.turns.map((turn) => (
            <div className="message-turn" key={turn.id}>
              <article className="user-message"><p>{turn.question}</p><time>{formatTime(turn.createdAt)}</time></article>
              <AssistantResponse
                view={assistantFromTurn(turn)}
                onOpenSources={() => onInspect(turn.requestId, "sources")}
                onOpenExecution={() => onInspect(turn.requestId, "execution")}
                onOpenAudit={() => onInspect(turn.requestId, "audit")}
                onFollowUp={onFollowUp}
                onRetry={() => onRetry(turn.question)}
                onOpenApproval={turn.requestId === pendingApprovalRequestId ? onOpenApproval : undefined}
                resultDisplay={resultDisplay}
              />
            </div>
          ))}
          {liveTurn && (
            <div className="message-turn live-turn">
              <article className="user-message"><p>{liveTurn.question}</p><time>{formatTime(liveTurn.startedAt)}</time></article>
              <AssistantResponse
                view={assistantFromLiveTurn(liveTurn)}
                onOpenSources={() => onInspect(liveTurn.requestId, "sources")}
                onOpenExecution={() => onInspect(liveTurn.requestId, "execution")}
                onOpenAudit={() => onInspect(liveTurn.requestId, "audit")}
                onFollowUp={onFollowUp}
                onRetry={() => onRetry(liveTurn.question)}
                onOpenApproval={liveTurn.requestId === pendingApprovalRequestId ? onOpenApproval : undefined}
                resultDisplay={resultDisplay}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

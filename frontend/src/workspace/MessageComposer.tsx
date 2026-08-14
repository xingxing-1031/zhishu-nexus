import { CornerDownLeft, SendHorizontal, Settings2, X } from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useRef } from "react";
import type { FollowUpContext } from "../conversations";
import type { ResultDisplayMode } from "../types";

export default function MessageComposer({
  question,
  maxRows,
  maxAllowedRows,
  resultDisplay,
  autoOpenEvidence,
  ready,
  running,
  followUpContext,
  onQuestion,
  onMaxRows,
  onResultDisplay,
  onAutoOpenEvidence,
  onCancelFollowUp,
  onSubmit,
}: {
  question: string;
  maxRows: number;
  maxAllowedRows: number;
  resultDisplay: ResultDisplayMode;
  autoOpenEvidence: boolean;
  ready: boolean;
  running: boolean;
  followUpContext: FollowUpContext | null;
  onQuestion: (value: string) => void;
  onMaxRows: (value: number) => void;
  onResultDisplay: (value: ResultDisplayMode) => void;
  onAutoOpenEvidence: (value: boolean) => void;
  onCancelFollowUp: () => void;
  onSubmit: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    const nextHeight = Math.min(128, Math.max(42, textarea.scrollHeight));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 128 ? "auto" : "hidden";
  }, [question]);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!running && ready && question.trim()) onSubmit();
    }
  }

  return (
    <div className="composer-wrap">
      <form className="message-composer" onSubmit={submit}>
        {followUpContext && (
          <div className="composer-context"><span>正在基于上一轮已验证结果追问</span><button type="button" onClick={onCancelFollowUp} aria-label="取消结果追问"><X size={14} /></button></div>
        )}
        <textarea
          ref={textareaRef}
          value={question}
          onChange={(event) => onQuestion(event.target.value)}
          onKeyDown={keyDown}
          rows={1}
          maxLength={800}
          placeholder={ready ? "向企析提问，系统会自动选择知识、数据或工具能力" : "服务正在准备，请稍候"}
          aria-label="向企析提问"
          disabled={!ready}
        />
        <div className="composer-toolbar">
          <details className="composer-options">
            <summary title="查询设置"><Settings2 size={16} /><span>查询设置</span></summary>
            <div className="composer-options-popover">
              <div className="query-setting-row">
                <label htmlFor="composerMaxRows">最大返回行数</label>
                <input id="composerMaxRows" type="number" min={1} max={maxAllowedRows} value={maxRows} onChange={(event) => onMaxRows(Number(event.target.value))} />
                <small>最多 {maxAllowedRows} 行</small>
              </div>
              <fieldset className="display-mode-setting">
                <legend>结果展示</legend>
                <div className="segmented-control">
                  {DISPLAY_MODES.map((mode) => (
                    <label key={mode.value}>
                      <input type="radio" name="resultDisplay" value={mode.value} checked={resultDisplay === mode.value} onChange={() => onResultDisplay(mode.value)} />
                      <span>{mode.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="toggle-setting">
                <span><strong>自动打开证据</strong><small>回答完成后展示引用与执行信息</small></span>
                <input type="checkbox" checked={autoOpenEvidence} onChange={(event) => onAutoOpenEvidence(event.target.checked)} />
              </label>
            </div>
          </details>
          <span className="composer-hint"><CornerDownLeft size={13} />Enter 发送 · Shift+Enter 换行</span>
          <button className="composer-submit" type="submit" disabled={!ready || running || !question.trim()} aria-label={running ? "任务执行中" : "发送问题"} title={running ? "任务执行中" : "发送问题"}>
            <SendHorizontal size={18} />
          </button>
        </div>
      </form>
      <p className="composer-disclaimer">企析可能会犯错。重要结论请核对右侧证据与审计信息。</p>
    </div>
  );
}

const DISPLAY_MODES: Array<{ value: ResultDisplayMode; label: string }> = [
  { value: "auto", label: "自动" },
  { value: "chart_table", label: "图表+表格" },
  { value: "table", label: "仅表格" },
];

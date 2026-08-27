import { CalendarRange, Globe2, Menu, PanelRightClose, PanelRightOpen, ShoppingBag } from "lucide-react";
import { BRAND } from "../brand";
import type { Overview } from "../types";

export default function WorkspaceHeader({
  overview,
  inspectorOpen,
  onOpenRail,
  onToggleInspector,
}: {
  overview: Overview | null;
  inspectorOpen: boolean;
  onOpenRail: () => void;
  onToggleInspector: () => void;
}) {
  return (
    <header className="workspace-topbar">
      <button className="topbar-icon rail-trigger" type="button" onClick={onOpenRail} aria-label="打开会话导航" title="会话导航">
        <Menu size={19} />
      </button>
      <div className="workspace-title">
        <span>{BRAND.workspaceName}</span>
        <small>知识、数据与工具在同一任务中协作</small>
      </div>
      {overview && (
        <div className="workspace-overview" title="演示数据概况">
          <span className="ov-item">
            <ShoppingBag size={15} />
            <b>{overview.order_count.toLocaleString("zh-CN")}</b>
            <small>订单</small>
          </span>
          <span className="ov-item">
            <Globe2 size={15} />
            <b>{overview.channel_count}</b>
            <small>渠道</small>
          </span>
          <span className="ov-item">
            <CalendarRange size={15} />
            <b>{overview.coverage_days}</b>
            <small>天数据跨度</small>
          </span>
        </div>
      )}
      <button className="topbar-icon" type="button" onClick={onToggleInspector} aria-label={inspectorOpen ? "关闭证据面板" : "打开证据面板"} title={inspectorOpen ? "关闭证据面板" : "打开证据面板"}>
        {inspectorOpen ? <PanelRightClose size={19} /> : <PanelRightOpen size={19} />}
      </button>
    </header>
  );
}

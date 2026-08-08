import {
  Activity,
  BookOpenText,
  ClipboardList,
  LogOut,
  ShieldCheck,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Role, SessionInfo } from "./types";

export type Page = "workspace" | "audit" | "metrics";
export type VisualStatus =
  | "success"
  | "warning"
  | "danger"
  | "neutral"
  | "running";

export function Header({
  session,
  online,
  page,
  onPage,
  onLogout,
}: {
  session: SessionInfo;
  online: boolean;
  page: Page;
  onPage: (page: Page) => void;
  onLogout: () => void;
}) {
  const isAdmin = session.role === "admin";
  return (
    <header className="app-header">
      <button className="brand" type="button" onClick={() => onPage("workspace")}>
        <span className="logo-mark">析</span>
        <span className="brand-name">零售运营分析台</span>
        <StatusPill status={isAdmin ? "warning" : "neutral"}>
          {isAdmin ? "管理员视角" : session.public_demo_mode ? "公网演示" : "受控访问"}
        </StatusPill>
      </button>

      {isAdmin && (
        <nav className="main-nav" aria-label="主要页面">
          <NavButton active={page === "workspace"} onClick={() => onPage("workspace")} icon={<Activity />}>
            分析工作台
          </NavButton>
          <NavButton active={page === "audit"} onClick={() => onPage("audit")} icon={<ClipboardList />}>
            审计记录
          </NavButton>
          <NavButton active={page === "metrics"} onClick={() => onPage("metrics")} icon={<BookOpenText />}>
            指标口径
          </NavButton>
        </nav>
      )}

      <div className="header-status">
        <span className={`service-dot ${online ? "online" : "offline"}`} />
        <span>{online ? "服务在线" : "服务未就绪"}</span>
        <span className="header-divider" />
        <strong>{roleLabel(session.role)}</strong>
        <span className="header-user">{session.user_id}</span>
        {!session.public_demo_mode && (
          <button className="icon-text-button" type="button" onClick={onLogout} title="退出登录">
            <LogOut size={15} />
            <span>退出登录</span>
          </button>
        )}
      </div>
    </header>
  );
}

function NavButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button className={`nav-button ${active ? "active" : ""}`} type="button" onClick={onClick}>
      {icon}
      <span>{children}</span>
    </button>
  );
}

export function StatusPill({
  status,
  children,
}: {
  status: VisualStatus;
  children: ReactNode;
}) {
  return <span className={`status-pill ${status}`}>{children}</span>;
}

export function KpiCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="kpi-card">
      <span>{label}</span>
      <strong className="mono">{value}</strong>
    </div>
  );
}

export function TrustCard() {
  return (
    <div className="trust-card">
      <div>
        <ShieldCheck size={16} />
        <strong>可信说明</strong>
      </div>
      <p>只读 · 可审计 · 业务口径受约束 · 查询经过安全与一致性校验</p>
    </div>
  );
}

export function Drawer({
  title,
  subtitle,
  width = "wide",
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  width?: "normal" | "wide";
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className={`drawer ${width}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="mono">{subtitle}</p>}
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="关闭">
            <X size={18} />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}

export function LoadingBlock({ text = "正在读取数据" }: { text?: string }) {
  return (
    <div className="loading-block" role="status">
      <span className="spinner" />
      <span>{text}</span>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function roleLabel(role: Role): string {
  return role === "admin" ? "管理员" : "分析员";
}

export function outcomeVisualStatus(status: string): VisualStatus {
  if (status === "succeeded" || status === "completed") return "success";
  if (status === "pending" || status === "approval_required" || status === "degraded") return "warning";
  if (status === "running" || status === "started") return "running";
  if (status === "rejected" || status === "failed") return "danger";
  return "neutral";
}

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
    <>
      <aside className="app-sidebar" aria-label="主导航">
        <button className="sidebar-brand" type="button" onClick={() => onPage("workspace")}>
          <span className="logo-mark">析</span>
          <span><strong>企析</strong><small>企业专业智能助理</small></span>
        </button>
        <div className="sidebar-context"><span className="sidebar-context-dot" />{session.public_demo_mode ? "公网演示环境" : "受控访问环境"}</div>
        <nav className="sidebar-nav" aria-label="主要页面">
          <NavButton active={page === "workspace"} onClick={() => onPage("workspace")} icon={<Activity />}>
            智能工作台
          </NavButton>
          {isAdmin && <NavButton active={page === "audit"} onClick={() => onPage("audit")} icon={<ClipboardList />}>
            审计记录
          </NavButton>}
          {isAdmin && <NavButton active={page === "metrics"} onClick={() => onPage("metrics")} icon={<BookOpenText />}>
            指标口径
          </NavButton>}
        </nav>
        <div className="sidebar-footer">
          <button className="sidebar-utility" type="button" onClick={onLogout}><LogOut size={16} />退出登录</button>
        </div>
      </aside>
      <header className="app-header">
        <div className="mobile-brand"><span className="logo-mark">析</span><strong>企析</strong></div>
        <div className="header-title"><span>{page === "workspace" ? "智能工作台" : page === "audit" ? "审计记录" : "指标口径"}</span><small>企业知识与经营分析</small></div>
        <div className="header-status">
          <span className={`service-dot ${online ? "online" : "offline"}`} />
          <span>{online ? "服务在线" : "服务未就绪"}</span>
          <span className="header-divider" />
          <strong>{roleLabel(session.role)}</strong><span className="header-user">{session.user_id}</span>
          <button className="header-logout" type="button" onClick={onLogout} title="退出登录" aria-label="退出登录"><LogOut size={16} /></button>
        </div>
      </header>
      {isAdmin && <nav className="mobile-nav" aria-label="移动端主要页面">
        <NavButton active={page === "workspace"} onClick={() => onPage("workspace")} icon={<Activity />}>分析</NavButton>
        <NavButton active={page === "audit"} onClick={() => onPage("audit")} icon={<ClipboardList />}>审计</NavButton>
        <NavButton active={page === "metrics"} onClick={() => onPage("metrics")} icon={<BookOpenText />}>口径</NavButton>
      </nav>}
    </>
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

export function TrustCard({ publicDemo }: { publicDemo: boolean }) {
  return (
    <div className="trust-card">
      <div>
        <ShieldCheck size={16} />
        <strong>可信说明</strong>
      </div>
      <p>{publicDemo ? "公开演示提供两种受控身份；知识、查询、审批和审计均由服务端校验。" : "只读 · 可审计 · 企业证据可引用 · 查询经过安全与一致性校验"}</p>
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

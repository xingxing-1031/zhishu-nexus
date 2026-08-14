import { LockKeyhole, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "./api";
import { BrandMark, BRAND } from "./brand";
import type { SessionInfo } from "./types";

const demoAccounts = [
  {
    username: "analyst-demo",
    password: "DemoAnalyst2026!",
    title: "分析员",
    description: "经营指标、趋势、渠道与商品分析；敏感退款原因会被权限拦截。",
  },
  {
    username: "admin-demo",
    password: "DemoAdmin2026!",
    title: "管理员",
    description: "包含分析员能力，可处理审批并查看审计记录与敏感退款原因。",
  },
] as const;

const TRUST_POINTS = ["自然语言对话", "知识检索", "经营分析", "受控工具调用"];

export default function LoginPage({ onLogin }: { onLogin: (session: SessionInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      onLogin(await api.login(username, password));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand-panel">
          <div className="login-brand">
            <BrandMark size="large" />
            <h1>{BRAND.productName}</h1>
          </div>
          <p className="login-hero">把企业问题交给知枢</p>
          <p className="login-tagline">{BRAND.positioning}。知枢 Nexus 会根据问题自动选择合适的知识、数据和工具，并保留可核验的依据与执行过程。</p>
          <ul className="login-points">
            {TRUST_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
          <div className="login-demo-heading">
            <span className="login-demo-label">选择演示身份</span>
          </div>
          <div className="demo-account-list" aria-label="公开演示账号">
            {demoAccounts.map((account) => (
              <button
                className="demo-account"
                type="button"
                key={account.username}
                onClick={() => {
                  setUsername(account.username);
                  setPassword(account.password);
                }}
              >
                <span><strong>{account.title}</strong><small>{account.description}</small></span>
                <code>{account.username}</code>
              </button>
            ))}
          </div>
        </div>

        <div className="login-form-area">
          <p className="login-subtitle">登录后进入受控的{BRAND.workspaceSubtitle}</p>
          <label htmlFor="username">用户名</label>
          <div className="input-with-icon">
            <UserRound size={16} />
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入用户名"
              required
            />
          </div>
          <label htmlFor="password">密码</label>
          <div className="input-with-icon">
            <LockKeyhole size={16} />
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              required
            />
          </div>
          {error && <p className="form-error">{error}</p>}
          <button className="primary-button login-submit" type="submit" disabled={submitting}>
            {submitting ? "正在进入" : "进入知枢工作台"}
          </button>
          <div className="login-notice">
            <span className="service-dot online" />
            <p>公开演示数据 · 角色、审批与审计均由服务器校验</p>
          </div>
        </div>
      </form>
    </main>
  );
}

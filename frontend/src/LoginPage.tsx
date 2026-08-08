import { LockKeyhole, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import { api } from "./api";
import type { SessionInfo } from "./types";

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
        <div className="login-brand">
          <span className="logo-mark large">析</span>
          <h1>零售运营分析台</h1>
        </div>
        <p className="login-subtitle">请登录后继续使用受控分析功能</p>
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
          {submitting ? "正在登录" : "登录"}
        </button>
        <div className="login-notice">
          <span className="service-dot online" />
          <p>服务连接正常 · 角色由服务器校验，不允许通过请求参数修改</p>
        </div>
      </form>
    </main>
  );
}

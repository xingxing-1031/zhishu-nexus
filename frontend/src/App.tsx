import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { AuditPage, MetricsPage } from "./AdminPages";
import { Header, LoadingBlock, type Page } from "./components";
import { BrandMark, BRAND } from "./brand";
import LoginPage from "./LoginPage";
import type { Overview, SessionInfo } from "./types";
import Workspace from "./Workspace";

export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [online, setOnline] = useState(false);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [page, setPage] = useState<Page>("workspace");

  async function bootstrap() {
    setLoading(true);
    try {
      const health = await api.health();
      setOnline(health.status === "ok");
      const activeSession = await api.session();
      setSession(activeSession);
      setNeedsLogin(false);
      try {
        await Promise.race([
          api.ready(),
          new Promise((_, reject) => window.setTimeout(() => reject(new Error("readiness timeout")), 3000)),
        ]);
        setReady(true);
      } catch {
        setReady(false);
      }
      try {
        setOverview(await Promise.race([
          api.overview(),
          new Promise<Overview>((_, reject) => window.setTimeout(() => reject(new Error("overview timeout")), 3000)),
        ]));
      } catch {
        setOverview(null);
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setNeedsLogin(true);
        setOnline(true);
      } else {
        setOnline(false);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void bootstrap(); }, []);

  async function logout() {
    await api.logout();
    setSession(null);
    setNeedsLogin(true);
    setPage("workspace");
  }

  function navigate(nextPage: Page) {
    if (nextPage !== "workspace" && session?.role !== "admin") return;
    setPage(nextPage);
  }

  if (loading) {
    return <div className="app-loading"><BrandMark size="large" /><LoadingBlock text={`正在连接${BRAND.chineseName}服务`} /></div>;
  }
  if (needsLogin || session === null) {
    return <LoginPage onLogin={(activeSession) => { setSession(activeSession); setNeedsLogin(false); void bootstrap(); }} />;
  }

  if (page === "workspace") {
    return (
      <Workspace
        session={session}
        overview={overview}
        ready={ready}
        online={online}
        onPage={navigate}
        onLogout={() => void logout()}
      />
    );
  }

  return (
    <div className="app-shell admin-shell-mode">
      <Header session={session} online={online && ready} page={page} onPage={navigate} onLogout={() => void logout()} />
      {page === "audit" && session.role === "admin" && <AuditPage />}
      {page === "metrics" && session.role === "admin" && <MetricsPage />}
    </div>
  );
}

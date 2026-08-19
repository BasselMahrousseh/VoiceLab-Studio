import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { get } from "./api";
import { useAuth } from "./auth";
import Logo from "./components/Logo";
import { Spinner } from "./components/widgets";
import Datasets from "./pages/Datasets";
import Analytics from "./pages/Analytics";
import ExportPage from "./pages/ExportPage";
import Login from "./pages/Login";
import Recorder from "./pages/Recorder";
import Review from "./pages/Review";
import Scripts from "./pages/Scripts";
import Settings from "./pages/Settings";
import Studio from "./pages/Studio";
import Team from "./pages/Team";
import { AppStatus } from "./types";
import { formatDuration } from "./format";

export { formatDuration };
export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="app-loading">
        <Logo height={72} />
        <Spinner label="Loading e& Lahja Studio…" />
      </div>
    );
  }
  if (!user) return <Login />;
  if (user.role === "recorder") return <Recorder />;
  return <AdminShell />;
}

function AdminShell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("lahja_theme") as "light" | "dark") || "light"
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("lahja_theme", theme);
  }, [theme]);

  const refresh = useCallback(() => {
    get<AppStatus>("/api/status")
      .then((s) => {
        setStatus(s);
        setError("");
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo height={54} />
        </div>
        <nav>
          <NavLink to="/datasets">📁 Datasets</NavLink>
          <NavLink to="/team">👥 Team</NavLink>
          <NavLink to="/analytics">📊 Analytics</NavLink>
          <NavLink to="/studio">🎙️ Studio</NavLink>
          <NavLink to="/scripts">📜 Script library</NavLink>
          <NavLink to="/review">🧪 Review</NavLink>
          <NavLink to="/export">📦 Export</NavLink>
          <NavLink to="/settings">⚙️ Settings</NavLink>
        </nav>
        <div className="sidebar-status">
          {status && (
            <>
              <div className="pill-row">
                <span className={`pill ${status.llm_configured ? "ok" : "off"}`}>
                  LLM {status.llm_configured ? "ready" : "off"}
                </span>
                <span className={`pill ${status.asr_configured ? "ok" : "off"}`}>
                  ASR {status.asr_configured ? "ready" : "off"}
                </span>
              </div>
              <div className="muted small">
                {status.accepted_count} accepted · {formatDuration(status.accepted_duration_sec)}
              </div>
            </>
          )}
          <div className="user-box">
            <div className="user-line">
              <span className="avatar">{(user?.display_name || user?.username || "?")[0]?.toUpperCase()}</span>
              <div className="grow">
                <div className="user-name">{user?.display_name || user?.username}</div>
                <div className="muted small">admin</div>
              </div>
            </div>
            <button className="btn ghost small logout-btn" onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}>
              {theme === "light" ? "Dark mode" : "Light mode"}
            </button>
            <button className="btn ghost small logout-btn" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="content">
        {error && <div className="banner error">API unreachable: {error}</div>}
        <div className="route-fade" key={location.pathname}>
          <Routes>
            <Route path="/" element={<Navigate to="/datasets" replace />} />
            <Route path="/datasets" element={<Datasets status={status} />} />
            <Route path="/team" element={<Team />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/studio" element={<Studio status={status} onChanged={refresh} />} />
            <Route path="/scripts" element={<Scripts status={status} />} />
            <Route path="/review" element={<Review status={status} onChanged={refresh} />} />
            <Route path="/export" element={<ExportPage status={status} />} />
            <Route path="/settings" element={<Settings status={status} />} />
            <Route path="*" element={<Navigate to="/datasets" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

import { FormEvent, useState } from "react";
import { useAuth } from "../auth";
import Logo from "../components/Logo";
import { Spinner } from "../components/widgets";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <form className="login-card fade-in" onSubmit={submit}>
        <div className="login-brand">
          <Logo height={52} />
          <div className="login-title">
            <b>Lahja</b> Studio
          </div>
          <div className="muted small">Emirati voice dataset recording</div>
        </div>
        <label className="field">
          <span>Username</span>
          <input
            className="input"
            autoFocus
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="your username"
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </label>
        {error && <div className="banner error">{error}</div>}
        <button className="btn record big login-btn" type="submit" disabled={busy || !username || !password}>
          {busy ? <Spinner label="Signing in…" /> : "Sign in"}
        </button>
      </form>
      <div className="login-foot muted small">e& Lahja Studio</div>
    </div>
  );
}

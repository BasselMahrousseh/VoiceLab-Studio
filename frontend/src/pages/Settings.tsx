import { useEffect, useState } from "react";
import { get, patch } from "../api";
import { Chip, Spinner } from "../components/widgets";
import { AppStatus, SessionInfo } from "../types";

export default function Settings({ status }: { status: AppStatus | null }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [policy, setPolicy] = useState("");
  const [defaultPolicy, setDefaultPolicy] = useState("");
  const [savedPolicy, setSavedPolicy] = useState("");
  const [policyBusy, setPolicyBusy] = useState(false);
  const [policyMessage, setPolicyMessage] = useState("");
  const [policyError, setPolicyError] = useState("");

  useEffect(() => {
    get<SessionInfo[]>("/api/sessions").then(setSessions).catch(() => undefined);
    get<{ text: string; default_text: string }>("/api/policy")
      .then((p) => {
        setPolicy(p.text);
        setSavedPolicy(p.text);
        setDefaultPolicy(p.default_text);
      })
      .catch((e) => setPolicyError(e.message));
  }, []);

  const savePolicy = async () => {
    setPolicyBusy(true);
    setPolicyError("");
    setPolicyMessage("");
    try {
      const response = await patch<{ text: string; default_text: string }>("/api/policy", {
        text: policy,
      });
      setPolicy(response.text);
      setSavedPolicy(response.text);
      setDefaultPolicy(response.default_text);
      setPolicyMessage("Global text policy saved. New AI generations will use it immediately.");
    } catch (e) {
      setPolicyError((e as Error).message);
    } finally {
      setPolicyBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Settings & status</h1>
      </div>

      <div className="panel">
        <h3>Services</h3>
        <div className="kv-grid">
          <span className="muted">Script generation LLM</span>
          <span>
            {status?.llm_configured ? (
              <Chip tone="ok">configured · {status.llm_model}</Chip>
            ) : (
              <Chip tone="off">not configured — set AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / LLM_DEPLOYMENT in .env</Chip>
            )}
          </span>
          <span className="muted">ASR verification (Whisper)</span>
          <span>
            {status?.asr_configured ? (
              <Chip tone="ok">configured · {status.asr_model}</Chip>
            ) : (
              <Chip tone="off">not configured — set ASR_DEPLOYMENT in .env</Chip>
            )}
          </span>
          <span className="muted">Data directory</span>
          <span className="mono small">{status?.data_dir}</span>
          <span className="muted">App version</span>
          <span>
            {status?.version} · dataset {status?.dataset_version}
          </span>
          <span className="muted">Totals</span>
          <span>
            {status?.scripts_total} scripts · {status?.recordings_total} recordings ·{" "}
            {status?.accepted_count} accepted
          </span>
        </div>
      </div>

      <h2 className="section-head">Recent sessions</h2>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>Started</th>
            <th>Ended</th>
            <th>Takes</th>
            <th>Accepted</th>
            <th>Room tone</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id}>
              <td>{s.id}</td>
              <td className="muted small">{new Date(s.started_at).toLocaleString()}</td>
              <td className="muted small">{s.ended_at ? new Date(s.ended_at).toLocaleString() : "active"}</td>
              <td>{s.recording_count}</td>
              <td>{s.accepted_count}</td>
              <td>
                {s.room_tone_dbfs != null ? (
                  <Chip tone={s.room_tone_status === "ok" ? "ok" : "warn"}>{s.room_tone_dbfs} dBFS</Chip>
                ) : (
                  <span className="muted small">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="section-head">Text policy</h2>
      <div className="panel">
        <p className="muted small">
          This is the global transcript policy. It is persisted with application data and passed
          to every AI generation request. Dataset-specific additions can be entered when a dataset
          is created or edited. Structural safety checks such as duplicate detection remain enforced
          by the application.
        </p>
        <textarea
          className="input policy-editor"
          rows={22}
          value={policy}
          onChange={(event) => {
            setPolicy(event.target.value);
            setPolicyMessage("");
          }}
          placeholder="Loading policy…"
        />
        {policyError && <div className="banner error">{policyError}</div>}
        {policyMessage && <div className="banner info">{policyMessage}</div>}
        <div className="row gap wrap" style={{ marginTop: 10 }}>
          <button
            className="btn accept"
            onClick={savePolicy}
            disabled={policyBusy || !policy.trim() || policy === savedPolicy}
          >
            {policyBusy ? <Spinner label="Saving policy…" /> : "Save global policy"}
          </button>
          <button
            className="btn ghost"
            onClick={() => {
              setPolicy(defaultPolicy);
              setPolicyMessage("The shipped default is loaded. Save to apply it.");
            }}
            disabled={!defaultPolicy || policy === defaultPolicy}
          >
            Restore shipped default
          </button>
          {policy !== savedPolicy && <span className="chip warn">Unsaved changes</span>}
        </div>
      </div>
    </div>
  );
}

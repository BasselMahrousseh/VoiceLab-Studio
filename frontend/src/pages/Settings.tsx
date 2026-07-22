import { useEffect, useState } from "react";
import { get } from "../api";
import { Chip } from "../components/widgets";
import { AppStatus, SessionInfo } from "../types";

export default function Settings({ status }: { status: AppStatus | null }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [policy, setPolicy] = useState("");

  useEffect(() => {
    get<SessionInfo[]>("/api/sessions").then(setSessions).catch(() => undefined);
    get<{ text: string }>("/api/policy").then((p) => setPolicy(p.text)).catch(() => undefined);
  }, []);

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
        <pre className="policy-text">{policy || "Loading…"}</pre>
      </div>
    </div>
  );
}

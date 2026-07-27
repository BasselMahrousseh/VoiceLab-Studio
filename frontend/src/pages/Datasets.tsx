import { useCallback, useEffect, useState } from "react";
import { get, patch, post } from "../api";
import { Modal, Spinner } from "../components/widgets";
import { AppStatus, Dataset, User } from "../types";
import GenAIWizard from "./GenAIWizard";

function fmtHours(sec: number): string {
  const h = sec / 3600;
  if (h >= 1) return `${h.toFixed(1)} h`;
  if (sec >= 60) return `${Math.round(sec / 60)} min`;
  return `${Math.round(sec)} s`;
}

const DEFAULT_INSTRUCTIONS = `• Record in a quiet room with no echo, fans, or background voices.
• Keep a steady hand-width distance from the microphone.
• Read the sentence exactly as shown, in natural Emirati dialect.
• Speak at a calm, even pace — don't rush the ends of sentences.
• If you stumble or mispronounce, just press Restart and read it again.
• Leave a short beat of silence before you start and after you finish.`;

export default function Datasets({ status }: { status: AppStatus | null }) {
  const [items, setItems] = useState<Dataset[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [genaiOpen, setGenaiOpen] = useState(false);
  const [genaiDatasetId, setGenaiDatasetId] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    get<Dataset[]>("/api/datasets").then(setItems).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const open = items.find((d) => d.id === openId) || null;

  return (
    <div className="page">
      <div className="row spread page-head">
        <div>
          <h1>Datasets</h1>
          <p className="muted small">
            A dataset is a set of sentences to record, its recording instructions, and the recorders
            assigned to it.
          </p>
        </div>
        <div className="row gap">
          <button className="btn ghost" onClick={() => setCreateOpen(true)}>
            ＋ New (manual)
          </button>
          <button className="btn record" onClick={() => { setGenaiDatasetId(null); setGenaiOpen(true); }}>
            ✨ Generate with GenAI
          </button>
        </div>
      </div>
      {error && <div className="banner error">{error}</div>}

      <div className="card-grid">
        {items.map((d) => {
          const pct = d.script_count ? Math.round((d.accepted_count / d.script_count) * 100) : 0;
          return (
            <button key={d.id} className="ds-card lift" onClick={() => setOpenId(d.id)}>
              <div className="row spread">
                <h3>{d.name}</h3>
                <span className={`chip ${d.status === "active" ? "ok" : "off"}`}>{d.status}</span>
              </div>
              {d.description && <p className="muted small ds-desc">{d.description}</p>}
              <div className="progress-track thin">
                <div className="progress-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="row gap ds-stats muted small">
                <span>📜 {d.script_count} scripts</span>
                <span>✓ {d.accepted_count} accepted</span>
                <span>🎙️ {d.recorder_count} recorders</span>
              </div>
              <div className="row gap ds-stats muted small">
                <span>⏺ recorded {fmtHours(d.accepted_duration_sec)}</span>
                {d.target_sample_count > 0 && (
                  <span>
                    🎯 target {d.target_sample_count.toLocaleString()} ·{" "}
                    {fmtHours(d.target_sample_count * d.target_avg_duration_sec)}
                  </span>
                )}
              </div>
            </button>
          );
        })}
        {!items.length && (
          <div className="panel center-panel muted">No datasets yet — create your first one.</div>
        )}
      </div>

      {createOpen && (
        <CreateDatasetModal status={status} onClose={() => setCreateOpen(false)} onCreated={(id) => { load(); setCreateOpen(false); setOpenId(id); }} />
      )}
      {genaiOpen && (
        <GenAIWizard
          status={status}
          dataset={items.find((d) => d.id === genaiDatasetId) ?? null}
          onClose={() => setGenaiOpen(false)}
          onCreated={(id) => { load(); setGenaiOpen(false); setGenaiDatasetId(null); setOpenId(id); }}
        />
      )}
      {open && (
        <DatasetDetail
          dataset={open}
          status={status}
          onClose={() => setOpenId(null)}
          onChanged={load}
          onGenerate={() => {
            setGenaiDatasetId(open.id);
            setOpenId(null);
            setGenaiOpen(true);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function CreateDatasetModal({
  status,
  onClose,
  onCreated,
}: {
  status: AppStatus | null;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [form, setForm] = useState({
    name: "",
    description: "",
    dialect: "emirati",
    instructions: DEFAULT_INSTRUCTIONS,
  });
  const [scripts, setScripts] = useState("");
  const [style, setStyle] = useState("neutral");
  const [domain, setDomain] = useState("customer_support");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const create = async () => {
    if (!form.name.trim()) {
      setError("Please give the dataset a name.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const ds = await post<Dataset>("/api/datasets", form);
      const lines = scripts.split("\n").filter((l) => l.trim());
      if (lines.length) {
        const r = await post<{ imported: number; skipped: unknown[] }>(
          `/api/datasets/${ds.id}/scripts`,
          { text: scripts, style, domain, dialect: form.dialect }
        );
        if (r.skipped.length) {
          setError(`Created. Imported ${r.imported} scripts, ${r.skipped.length} skipped (policy issues).`);
        }
      }
      onCreated(ds.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title="New dataset" onClose={onClose} wide>
      <div className="form-grid">
        <label>
          Dataset name
          <input
            className="input"
            placeholder="Emirati Customer Support v1"
            value={form.name}
            maxLength={200}
            required
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          Dialect
          <select className="input" value={form.dialect} onChange={(e) => setForm({ ...form, dialect: e.target.value })}>
            {(status?.enums.dialects ?? ["emirati", "msa", "mixed"]).map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
        <label className="span2">
          Description (optional)
          <input className="input" placeholder="Short note about the goal of this dataset" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </label>
        <label className="span2">
          Recording instructions — shown to recorders before they record
          <textarea className="input" rows={6} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
        </label>
        <div className="span2 sub-head">Starter scripts (optional — you can add more later)</div>
        <label>
          Style
          <select className="input" value={style} onChange={(e) => setStyle(e.target.value)}>
            {(status?.enums.styles ?? ["neutral"]).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Domain
          <select className="input" value={domain} onChange={(e) => setDomain(e.target.value)}>
            {(status?.enums.domains ?? ["general"]).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="span2">
          One sentence per line (Arabic)
          <textarea className="input arabic" dir="rtl" rows={5} placeholder={"هلا شحالك اليوم؟\nشو تبغي أسويلك؟"} value={scripts} onChange={(e) => setScripts(e.target.value)} />
        </label>
      </div>
      {error && <div className="banner warn">{error}</div>}
      <div className="row gap modal-actions">
        <button className="btn accept" onClick={create} disabled={busy || !form.name.trim()}>
          {busy ? <Spinner label="Creating…" /> : "Create dataset"}
        </button>
        <button className="btn ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
function DatasetDetail({
  dataset,
  status,
  onClose,
  onChanged,
  onGenerate,
}: {
  dataset: Dataset;
  status: AppStatus | null;
  onClose: () => void;
  onChanged: () => void;
  onGenerate: () => void;
}) {
  const [instructions, setInstructions] = useState(dataset.instructions);
  const [recorders, setRecorders] = useState<User[]>([]);
  const [allRecorders, setAllRecorders] = useState<User[]>([]);
  const [assignId, setAssignId] = useState(0);
  const [scripts, setScripts] = useState("");
  const [style, setStyle] = useState("neutral");
  const [domain, setDomain] = useState("customer_support");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadRecorders = useCallback(() => {
    Promise.all([
      get<User[]>(`/api/datasets/${dataset.id}/recorders`),
      get<User[]>("/api/auth/users"),
    ])
      .then(([assigned, users]) => {
        setRecorders(assigned);
        setAllRecorders(users.filter((user) => user.role === "recorder"));
      })
      .catch((e) => setError(e.message));
  }, [dataset.id]);
  useEffect(loadRecorders, [loadRecorders]);

  const saveInstructions = async () => {
    setError("");
    try {
      await patch(`/api/datasets/${dataset.id}`, { instructions });
      setMsg("Instructions saved.");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const addScripts = async () => {
    if (!scripts.trim()) {
      setError("Paste at least one sentence first.");
      return;
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await post<{ imported: number; skipped: unknown[] }>(
        `/api/datasets/${dataset.id}/scripts`,
        { text: scripts, style, domain, dialect: dataset.dialect }
      );
      setMsg(`Added ${r.imported} scripts (${r.skipped.length} skipped).`);
      setScripts("");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const assignRecorder = async () => {
    if (!assignId) return;
    const user = allRecorders.find((item) => item.id === assignId);
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await patch(`/api/auth/users/${assignId}`, { dataset_id: dataset.id });
      setMsg(`${user?.display_name || user?.username || "Recorder"} is now assigned to ${dataset.name}.`);
      setAssignId(0);
      loadRecorders();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const availableRecorders = allRecorders.filter((user) => user.dataset_id !== dataset.id);

  return (
    <Modal title={dataset.name} onClose={onClose} wide>
      <div className="detail-stats row gap wrap">
        <span className="chip">{dataset.dialect}</span>
        <span className="chip">📜 {dataset.script_count} scripts</span>
        <span className="chip ok">✓ {dataset.accepted_count} accepted · {fmtHours(dataset.accepted_duration_sec)}</span>
        <span className="chip">🎙️ {dataset.recorder_count} recorders</span>
        {dataset.target_sample_count > 0 && (
          <span className="chip accent">
            🎯 {dataset.target_sample_count.toLocaleString()} samples ·{" "}
            {fmtHours(dataset.target_sample_count * dataset.target_avg_duration_sec)}
          </span>
        )}
      </div>

      {error && <div className="banner error">{error}</div>}
      {msg && <div className="banner info">{msg}</div>}

      <h3 className="section-head">Recording instructions</h3>
      <textarea className="input" rows={6} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn accent small" onClick={saveInstructions}>
          Save instructions
        </button>
      </div>

      <div className="row spread section-head">
        <div>
          <h3>Add more data</h3>
          <div className="muted small">Paste sentences below or generate and review a new AI batch.</div>
        </div>
        <button className="btn record small" onClick={onGenerate}>✨ Generate with AI</button>
      </div>
      <div className="row gap">
        <select className="input" value={style} onChange={(e) => setStyle(e.target.value)}>
          {(status?.enums.styles ?? ["neutral"]).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={domain} onChange={(e) => setDomain(e.target.value)}>
          {(status?.enums.domains ?? ["general"]).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <textarea className="input arabic" dir="rtl" rows={4} style={{ marginTop: 8 }} placeholder={"سطر لكل جملة…"} value={scripts} onChange={(e) => setScripts(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn accent small" onClick={addScripts} disabled={busy || !scripts.trim()}>
          {busy ? <Spinner label="Adding…" /> : "Add pasted scripts"}
        </button>
      </div>

      <h3 className="section-head">Recorders</h3>
      <div className="recorder-list">
        {recorders.map((r) => (
          <div key={r.id} className="row spread recorder-item">
            <div>
              <b>{r.display_name || r.username}</b>{" "}
              <span className="muted small">@{r.username} · voice {r.speaker?.speaker_key}</span>
            </div>
            <span className={`chip ${r.active ? "ok" : "off"}`}>{r.active ? "active" : "disabled"}</span>
          </div>
        ))}
        {!recorders.length && <div className="muted small">No recorders assigned yet.</div>}
      </div>
      <div className="assign-recorder row gap wrap">
        <select
          className="input grow"
          value={assignId}
          onChange={(event) => setAssignId(Number(event.target.value))}
          disabled={!availableRecorders.length || dataset.script_count === 0}
        >
          <option value={0}>
            {dataset.script_count === 0
              ? "Add scripts before assigning a recorder"
              : availableRecorders.length
                ? "Select an existing recorder…"
                : "All recorders are already assigned here"}
          </option>
          {availableRecorders.map((user) => (
            <option key={user.id} value={user.id}>
              {user.display_name || user.username} (@{user.username})
              {user.dataset_name ? ` — currently ${user.dataset_name}` : ""}
            </option>
          ))}
        </select>
        <button className="btn accent small" onClick={assignRecorder} disabled={busy || !assignId || dataset.script_count === 0}>
          Assign to this dataset
        </button>
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>
        Assigning a recorder who already has a dataset moves them to this one.
      </div>
      <AddRecorder datasetId={dataset.id} onAdded={() => { loadRecorders(); onChanged(); }} />
    </Modal>
  );
}

// ---------------------------------------------------------------------------
function AddRecorder({ datasetId, onAdded }: { datasetId: number; onAdded: () => void }) {
  const [form, setForm] = useState({ username: "", password: "", display_name: "" });
  const [created, setCreated] = useState<{ username: string; password: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async () => {
    setError("");
    setBusy(true);
    try {
      await post<User>(`/api/datasets/${datasetId}/recorders`, form);
      setCreated({ username: form.username, password: form.password });
      setForm({ username: "", password: "", display_name: "" });
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="add-recorder">
      <div className="form-grid">
        <label>
          Username
          <input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="reader1" />
        </label>
        <label>
          Display name
          <input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="Full name" />
        </label>
        <label className="span2">
          Password
          <input className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="temporary password" />
        </label>
      </div>
      {error && <div className="banner error">{error}</div>}
      {created && (
        <div className="banner info small">
          Recorder <b>{created.username}</b> created. Share these credentials — username{" "}
          <code>{created.username}</code>, password <code>{created.password}</code>.
        </div>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn accept small" onClick={add} disabled={busy || !form.username || form.password.length < 4}>
          ＋ Create recorder
        </button>
      </div>
    </div>
  );
}

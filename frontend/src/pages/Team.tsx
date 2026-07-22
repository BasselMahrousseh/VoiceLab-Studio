import { useCallback, useEffect, useState } from "react";
import { get, patch, post } from "../api";
import { useAuth } from "../auth";
import { Modal, Spinner } from "../components/widgets";
import { Dataset, User } from "../types";

export default function Team() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    get<User[]>("/api/auth/users").then(setUsers).catch((e) => setError(e.message));
    get<Dataset[]>("/api/datasets").then(setDatasets).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const toggleActive = async (u: User) => {
    try {
      await patch(`/api/auth/users/${u.id}`, { active: !u.active });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="row spread page-head">
        <div>
          <h1>Team</h1>
          <p className="muted small">Admins manage everything. Recorders only see the recording view for their dataset.</p>
        </div>
        <button className="btn record" onClick={() => setAddOpen(true)}>
          ＋ Add user
        </button>
      </div>
      {error && <div className="banner error">{error}</div>}

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Username</th>
            <th>Role</th>
            <th>Dataset</th>
            <th>Last login</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.display_name || "—"}</td>
              <td className="mono small">{u.username}</td>
              <td>
                <span className={`chip ${u.role === "admin" ? "accent" : ""}`}>{u.role}</span>
              </td>
              <td className="muted small">{u.dataset_name || (u.role === "recorder" ? "—" : "")}</td>
              <td className="muted small">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}</td>
              <td>
                <span className={`chip ${u.active ? "ok" : "off"}`}>{u.active ? "active" : "disabled"}</span>
              </td>
              <td>
                <div className="row gap">
                  <button className="link-btn" onClick={() => setResetFor(u)}>
                    reset password
                  </button>
                  {u.id !== me?.id && (
                    <button className="link-btn" onClick={() => toggleActive(u)}>
                      {u.active ? "disable" : "enable"}
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {addOpen && (
        <AddUserModal datasets={datasets} onClose={() => setAddOpen(false)} onAdded={() => { load(); setAddOpen(false); }} />
      )}
      {resetFor && <ResetModal user={resetFor} onClose={() => setResetFor(null)} onDone={() => setResetFor(null)} />}
    </div>
  );
}

function AddUserModal({
  datasets,
  onClose,
  onAdded,
}: {
  datasets: Dataset[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [form, setForm] = useState({
    username: "",
    password: "",
    display_name: "",
    role: "recorder",
    dataset_id: datasets[0]?.id ?? 0,
    speaker_key: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        role: form.role,
      };
      if (form.role === "recorder") {
        payload.dataset_id = form.dataset_id || null;
        payload.speaker_key = form.speaker_key || form.username;
      }
      await post<User>("/api/auth/users", payload);
      onAdded();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title="Add user" onClose={onClose}>
      <div className="form-grid">
        <label>
          Role
          <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="recorder">recorder</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <label>
          Display name
          <input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </label>
        <label>
          Username
          <input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </label>
        <label>
          Password
          <input className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        {form.role === "recorder" && (
          <>
            <label>
              Assigned dataset
              <select className="input" value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: Number(e.target.value) })}>
                <option value={0}>— none —</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Voice key (optional)
              <input className="input" placeholder="defaults to username" value={form.speaker_key} onChange={(e) => setForm({ ...form, speaker_key: e.target.value })} />
            </label>
          </>
        )}
      </div>
      {error && <div className="banner error">{error}</div>}
      <div className="row gap" style={{ marginTop: 12 }}>
        <button className="btn accept" onClick={submit} disabled={busy || !form.username || form.password.length < 4}>
          {busy ? <Spinner label="Creating…" /> : "Create user"}
        </button>
        <button className="btn ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

function ResetModal({ user, onClose, onDone }: { user: User; onClose: () => void; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError("");
    try {
      await patch(`/api/auth/users/${user.id}`, { password });
      setDone(true);
      setTimeout(onDone, 1200);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Modal title={`Reset password — ${user.username}`} onClose={onClose}>
      {done ? (
        <div className="banner info">Password updated.</div>
      ) : (
        <>
          <label className="field">
            <span>New password</span>
            <input className="input" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="at least 4 characters" />
          </label>
          {error && <div className="banner error">{error}</div>}
          <div className="row gap" style={{ marginTop: 12 }}>
            <button className="btn accept" onClick={submit} disabled={password.length < 4}>
              Update password
            </button>
            <button className="btn ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

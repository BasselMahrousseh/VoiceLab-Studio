import { useCallback, useEffect, useState } from "react";
import { get, patch, post, remove } from "../api";
import { useAuth } from "../auth";
import { Modal, Spinner } from "../components/widgets";
import { Dataset, User } from "../types";

export default function Team() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [deleteFor, setDeleteFor] = useState<User | null>(null);
  const [savingDatasetFor, setSavingDatasetFor] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    get<User[]>("/api/auth/users").then(setUsers).catch((e) => setError(e.message));
    get<Dataset[]>("/api/datasets").then(setDatasets).catch((e) => setError(e.message));
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

  const assignDataset = async (u: User, datasetId: number) => {
    setSavingDatasetFor(u.id);
    setError("");
    try {
      await patch(`/api/auth/users/${u.id}`, { dataset_id: datasetId });
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSavingDatasetFor(null);
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
              <td className="muted small">
                {u.role === "recorder" ? (
                  <select
                    className="input dataset-assignment"
                    aria-label={`Dataset for ${u.username}`}
                    value={u.dataset_id ?? 0}
                    disabled={savingDatasetFor === u.id}
                    onChange={(e) => void assignDataset(u, Number(e.target.value))}
                  >
                    {!u.dataset_id && <option value={0}>Select dataset</option>}
                    {datasets.map((d) => (
                      <option
                        key={d.id}
                        value={d.id}
                        disabled={d.script_count === 0 && d.id !== u.dataset_id}
                      >
                        {d.name} · {d.script_count} scripts
                      </option>
                    ))}
                  </select>
                ) : (
                  ""
                )}
              </td>
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
                    <>
                      <button className="link-btn" onClick={() => toggleActive(u)}>
                        {u.active ? "disable" : "enable"}
                      </button>
                      <button className="link-btn danger-link" onClick={() => setDeleteFor(u)}>
                        delete
                      </button>
                    </>
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
      {deleteFor && (
        <DeleteUserModal
          user={deleteFor}
          onClose={() => setDeleteFor(null)}
          onDeleted={() => {
            setDeleteFor(null);
            load();
          }}
        />
      )}
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
  const eligibleDatasets = datasets.filter((d) => d.status === "active" && d.script_count > 0);
  const defaultDatasetId = eligibleDatasets[0]?.id ?? 0;
  const [form, setForm] = useState({
    username: "",
    password: "",
    display_name: "",
    role: "recorder",
    dataset_id: defaultDatasetId,
    speaker_key: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!form.dataset_id && defaultDatasetId) {
      setForm((current) => ({ ...current, dataset_id: defaultDatasetId }));
    }
  }, [defaultDatasetId, form.dataset_id]);

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
                {eligibleDatasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.script_count} scripts
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
      {form.role === "recorder" && !eligibleDatasets.length && (
        <div className="banner warn">Create an active dataset with scripts before adding a recorder.</div>
      )}
      <div className="row gap modal-actions">
        <button
          className="btn accept"
          onClick={submit}
          disabled={
            busy ||
            !form.username.trim() ||
            form.password.length < 4 ||
            (form.role === "recorder" && !form.dataset_id)
          }
        >
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

function DeleteUserModal({
  user,
  onClose,
  onDeleted,
}: {
  user: User;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await remove(`/api/auth/users/${user.id}`);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Delete user — ${user.username}`} onClose={onClose}>
      <div className="banner error">
        This permanently removes the login account. Historical speaker and recording identity is
        preserved for dataset traceability.
      </div>
      <label className="field">
        <span>
          Type <b>{user.username}</b> to confirm
        </span>
        <input
          className="input"
          value={confirmation}
          autoFocus
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      {error && <div className="banner error">{error}</div>}
      <div className="row gap modal-actions">
        <button
          className="btn danger"
          disabled={busy || confirmation !== user.username}
          onClick={submit}
        >
          {busy ? <Spinner label="Deleting…" /> : "Permanently delete user"}
        </button>
        <button className="btn ghost" disabled={busy} onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

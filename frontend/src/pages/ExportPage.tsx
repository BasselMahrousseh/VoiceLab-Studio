import { useCallback, useEffect, useState } from "react";
import { get, mediaUrl, post } from "../api";
import { formatDuration } from "../App";
import { Chip, MultiSelect, Spinner } from "../components/widgets";
import { AppStatus, Dataset, ExportBatch } from "../types";

export default function ExportPage({ status }: { status: AppStatus | null }) {
  const [batches, setBatches] = useState<ExportBatch[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [params, setParams] = useState({
    name: "",
    dataset_id: 0,
    sample_rate: 24000,
    trim_silence: true,
    normalize: "none",
    target_lufs: -20,
    dedupe_takes: true,
    include_qc_warning: true,
    styles: [] as string[],
    domains: [] as string[],
    make_zip: true,
  });

  const load = useCallback(() => {
    get<ExportBatch[]>("/api/exports").then(setBatches).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    get<Dataset[]>("/api/datasets")
      .then((rows) => {
        setDatasets(rows);
        setParams((current) => ({
          ...current,
          dataset_id: current.dataset_id || rows.find((dataset) => dataset.accepted_count > 0)?.id || rows[0]?.id || 0,
        }));
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (status) setParams((p) => ({ ...p, sample_rate: status.export_sample_rate }));
  }, [status]);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const batch = await post<ExportBatch>("/api/exports", params);
      if (batch.status === "failed") setError(batch.error);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Dataset export</h1>
        <p className="muted">
          Exports accepted recordings as mono PCM-16 WAV at the target rate, with{" "}
          <code>metadata.csv</code>, <code>metadata.jsonl</code>, <code>qc_report.json</code> and a
          dataset card. Masters stay untouched.
        </p>
      </div>

      <div className="panel">
        <div className="form-grid">
          <label>
            Export name
            <input className="input" placeholder="emirati_v1" value={params.name} onChange={(e) => setParams({ ...params, name: e.target.value })} />
          </label>
          <label>
            Dataset
            <select className="input" value={params.dataset_id} onChange={(e) => setParams({ ...params, dataset_id: Number(e.target.value) })}>
              <option value={0}>Select a dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} — {dataset.accepted_count} accepted
                </option>
              ))}
            </select>
          </label>
          <label>
            Target sample rate
            <select className="input" value={params.sample_rate} onChange={(e) => setParams({ ...params, sample_rate: Number(e.target.value) })}>
              {[16000, 22050, 24000, 44100, 48000].map((r) => (
                <option key={r} value={r}>
                  {r} Hz
                </option>
              ))}
            </select>
          </label>
          <label>
            Loudness
            <select className="input" value={params.normalize} onChange={(e) => setParams({ ...params, normalize: e.target.value })}>
              <option value="none">Keep original levels</option>
              <option value="peak">Peak normalize (−3 dBFS)</option>
              <option value="loudness">Loudness normalize (LUFS)</option>
            </select>
          </label>
          {params.normalize === "loudness" && (
            <label>
              Target LUFS
              <input type="number" className="input" value={params.target_lufs} onChange={(e) => setParams({ ...params, target_lufs: Number(e.target.value) })} />
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={params.trim_silence} onChange={(e) => setParams({ ...params, trim_silence: e.target.checked })} />
            Trim lead/trail silence (keep 0.2 s pad)
          </label>
          <label className="check">
            <input type="checkbox" checked={params.dedupe_takes} onChange={(e) => setParams({ ...params, dedupe_takes: e.target.checked })} />
            One take per script and speaker (latest accepted)
          </label>
          <label className="check">
            <input type="checkbox" checked={params.include_qc_warning} onChange={(e) => setParams({ ...params, include_qc_warning: e.target.checked })} />
            Include takes with QC warnings
          </label>
          <label className="check">
            <input type="checkbox" checked={params.make_zip} onChange={(e) => setParams({ ...params, make_zip: e.target.checked })} />
            Create zip archive
          </label>
          <label className="span2">
            Filter styles (empty = all)
            <MultiSelect options={status?.enums.styles ?? []} value={params.styles} onChange={(v) => setParams({ ...params, styles: v })} />
          </label>
          <label className="span2">
            Filter domains (empty = all)
            <MultiSelect options={status?.enums.domains ?? []} value={params.domains} onChange={(v) => setParams({ ...params, domains: v })} />
          </label>
        </div>
        {error && <div className="banner error">{error}</div>}
        <div className="row gap" style={{ marginTop: 12 }}>
          <button className="btn accent" onClick={run} disabled={busy || !params.dataset_id}>
            {busy ? <Spinner label="Exporting…" /> : "📦 Build export"}
          </button>
          <span className="muted small">
            {datasets.find((dataset) => dataset.id === params.dataset_id)?.accepted_count ?? 0} accepted recordings in the selected dataset ·{" "}
            {formatDuration(datasets.find((dataset) => dataset.id === params.dataset_id)?.accepted_duration_sec ?? 0)}
          </span>
        </div>
      </div>

      <h2 className="section-head">Past exports</h2>
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Dataset</th>
            <th>Created</th>
            <th>Clips</th>
            <th>Duration</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {batches.map((b) => (
            <tr key={b.id}>
              <td>{b.name}</td>
              <td className="small">
                {datasets.find((dataset) => dataset.id === Number(b.params?.dataset_id))?.name || "All / legacy"}
              </td>
              <td className="muted small">{new Date(b.created_at).toLocaleString()}</td>
              <td>{b.file_count}</td>
              <td>{b.stats?.total_duration_hms ?? "—"}</td>
              <td>
                <Chip tone={b.status === "done" ? "ok" : "bad"}>{b.status}</Chip>
              </td>
              <td>
                {b.zip_rel_path && (
                  <a className="btn ghost small" href={mediaUrl(`/api/exports/${b.id}/download`)}>
                    ⬇ zip
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

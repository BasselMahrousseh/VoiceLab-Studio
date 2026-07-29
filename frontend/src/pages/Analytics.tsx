import { useCallback, useEffect, useMemo, useState } from "react";
import { get } from "../api";
import PerformanceDashboardView from "../components/dashboard/PerformanceDashboardView";
import { fmtNum } from "../components/dashboard/Charts";
import { Spinner } from "../components/widgets";
import { Dataset, LeaderboardRow, PerformanceDashboard } from "../types";

type Metric = "completed" | "accepted" | "skipped" | "remaining" | "acceptance_rate";

export default function Analytics() {
  const [rows, setRows] = useState<LeaderboardRow[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PerformanceDashboard | null>(null);
  const [metric, setMetric] = useState<Metric>("completed");
  const [datasetId, setDatasetId] = useState<number | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (datasetId !== "") p.set("dataset_id", String(datasetId));
    if (dateFrom) p.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) p.set("date_to", new Date(`${dateTo}T23:59:59`).toISOString());
    return p.toString();
  }, [datasetId, dateFrom, dateTo]);

  const loadList = useCallback(() => {
    setLoading(true);
    setError("");
    const q = query ? `?${query}&metric=${metric}` : `?metric=${metric}`;
    Promise.all([
      get<LeaderboardRow[]>(`/api/analytics/leaderboard${q}`),
      get<Dataset[]>("/api/datasets"),
    ])
      .then(([leaderboard, ds]) => {
        setRows(leaderboard);
        setDatasets(ds);
        setSelectedId((prev) => prev ?? (leaderboard[0]?.user_id ?? null));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [metric, query]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    const q = query ? `?${query}` : "";
    get<PerformanceDashboard>(`/api/analytics/recorders/${selectedId}${q}`)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setDetailLoading(false));
  }, [selectedId, query]);

  return (
    <div className="page analytics-page">
      <div className="row spread page-head">
        <div>
          <h1>Recorder analytics</h1>
          <p className="muted small">
            Who is assigned what, how many scripts they finished, and how many they skipped.
          </p>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="dash-filters panel">
        <label>
          Dataset
          <select
            className="input"
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">All datasets</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          From
          <input
            className="input"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label>
          To
          <input
            className="input"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <label>
          Leaderboard by
          <select
            className="input"
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
          >
            <option value="completed">Finished scripts</option>
            <option value="accepted">Accepted clips</option>
            <option value="skipped">Skipped / deleted</option>
            <option value="remaining">Remaining</option>
            <option value="acceptance_rate">Acceptance %</option>
          </select>
        </label>
      </div>

      {loading ? (
        <Spinner label="Loading leaderboard…" />
      ) : (
        <div className="analytics-layout">
          <aside className="analytics-sidebar panel">
            <h2>Leaderboard</h2>
            <div className="analytics-rank-list">
              {rows.map((r, idx) => (
                <button
                  key={r.user_id}
                  type="button"
                  className={`analytics-rank-row ${selectedId === r.user_id ? "active" : ""}`}
                  onClick={() => setSelectedId(r.user_id)}
                >
                  <span className="analytics-rank-pos">#{idx + 1}</span>
                  <div className="grow">
                    <div className="analytics-rank-name">{r.display_name}</div>
                    <div className="muted small">
                      {r.dataset_name || "—"} · {fmtNum(r.completed ?? r.accepted)} done
                      {(r.skipped ?? 0) > 0 ? ` · ${fmtNum(r.skipped)} skipped` : ""}
                    </div>
                  </div>
                  <strong>{fmtNum(metric === "skipped" ? r.skipped : metric === "remaining" ? r.remaining : metric === "acceptance_rate" ? r.acceptance_rate : metric === "accepted" ? r.accepted : r.completed ?? r.accepted)}</strong>
                </button>
              ))}
              {!rows.length && <div className="muted small">No recorders yet.</div>}
            </div>
          </aside>

          <div className="analytics-detail">
            {detailLoading && <Spinner label="Loading recorder…" />}
            {!detailLoading && detail && (
              <>
                <div className="panel fade-in" style={{ marginBottom: 0 }}>
                  <div className="row spread">
                    <div>
                      <h2 style={{ margin: 0 }}>{detail.profile.display_name}</h2>
                      <p className="muted small" style={{ margin: "4px 0 0" }}>
                        {detail.profile.dataset_name || "No dataset"}
                        {detail.profile.last_active_at
                          ? ` · last active ${new Date(detail.profile.last_active_at).toLocaleString()}`
                          : ""}
                      </p>
                    </div>
                    <span className={`chip ${detail.profile.active ? "ok" : "off"}`}>
                      {detail.profile.status}
                    </span>
                  </div>
                </div>
                <PerformanceDashboardView data={detail} />
              </>
            )}
            {!detailLoading && !detail && (
              <div className="panel muted">Select a recorder to view analytics.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

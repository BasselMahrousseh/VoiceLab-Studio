import { useCallback, useEffect, useState } from "react";
import { get, patch, post } from "../api";
import { Chip, Modal, MultiSelect, Spinner } from "../components/widgets";
import { AppStatus, GenerateCandidate, Script, ScriptStats } from "../types";

const PAGE = 25;

export default function Scripts({ status }: { status: AppStatus | null }) {
  const [stats, setStats] = useState<ScriptStats | null>(null);
  const [items, setItems] = useState<Script[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState({ status: "", style: "", domain: "", search: "" });
  const [genOpen, setGenOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [edit, setEdit] = useState<Script | null>(null);
  const [error, setError] = useState("");

  const styles = status?.enums.styles ?? [];
  const domains = status?.enums.domains ?? [];

  const load = useCallback(() => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
    params.set("limit", String(PAGE));
    params.set("offset", String(page * PAGE));
    get<{ total: number; items: Script[] }>(`/api/scripts?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(e.message));
    get<ScriptStats>("/api/scripts/stats").then(setStats).catch(() => undefined);
  }, [filters, page]);

  useEffect(load, [load]);

  return (
    <div className="page">
      <div className="row spread page-head">
        <h1>Script bank</h1>
        <div className="row gap">
          <button className="btn ghost" onClick={() => setImportOpen(true)}>
            ⬆ Import
          </button>
          <button
            className="btn accent"
            onClick={() => setGenOpen(true)}
            disabled={!status?.llm_configured}
            title={status?.llm_configured ? "" : "Configure the LLM endpoint in .env first"}
          >
            ✨ Generate with LLM
          </button>
        </div>
      </div>
      {error && <div className="banner error">{error}</div>}

      {stats && (
        <div className="stat-row">
          <StatCard label="Total scripts" value={stats.total} />
          <StatCard label="New" value={stats.by_status.new ?? 0} />
          <StatCard label="Done" value={stats.by_status.done ?? 0} />
          <StatCard label="Flagged" value={stats.by_status.flagged ?? 0} />
          <StatCard
            label="Accepted audio"
            value={`${Math.round(stats.accepted_duration_sec / 60)} min`}
          />
          <BarCard label="By style" data={stats.by_style} />
          <BarCard label="By length" data={stats.by_length} />
        </div>
      )}

      <div className="row gap filter-bar">
        <select className="input" value={filters.status} onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setPage(0); }}>
          <option value="">All statuses</option>
          {["new", "recorded", "done", "flagged", "retired"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={filters.style} onChange={(e) => { setFilters({ ...filters, style: e.target.value }); setPage(0); }}>
          <option value="">All styles</option>
          {styles.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={filters.domain} onChange={(e) => { setFilters({ ...filters, domain: e.target.value }); setPage(0); }}>
          <option value="">All domains</option>
          {domains.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <input
          className="input grow"
          placeholder="Search text or ID…"
          value={filters.search}
          onChange={(e) => { setFilters({ ...filters, search: e.target.value }); setPage(0); }}
        />
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th className="grow">Text</th>
            <th>Style</th>
            <th>Domain</th>
            <th>Len</th>
            <th>Takes</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id} onClick={() => setEdit(s)} className="clickable">
              <td className="mono small">{s.script_id}</td>
              <td className="arabic cell-text" dir="rtl">{s.display_text}</td>
              <td>{s.style}</td>
              <td>{s.domain}</td>
              <td>{s.length_bucket}</td>
              <td>{s.take_count}</td>
              <td>
                <Chip tone={s.status === "done" ? "ok" : s.status === "flagged" ? "bad" : ""}>{s.status}</Chip>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row gap pager">
        <button className="btn ghost small" disabled={page === 0} onClick={() => setPage(page - 1)}>
          ← Prev
        </button>
        <span className="muted small">
          {page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total}
        </span>
        <button className="btn ghost small" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>
          Next →
        </button>
      </div>

      {genOpen && <GenerateModal status={status} onClose={() => setGenOpen(false)} onImported={load} />}
      {importOpen && <ImportModal status={status} onClose={() => setImportOpen(false)} onImported={load} />}
      {edit && <EditModal script={edit} styles={styles} domains={domains} onClose={() => setEdit(null)} onSaved={load} />}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="muted small">{label}</div>
    </div>
  );
}

function BarCard({ label, data }: { label: string; data: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(data));
  return (
    <div className="stat-card bar-card">
      <div className="muted small">{label}</div>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="bar-row">
          <span className="small">{k}</span>
          <div className="bar">
            <div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="small muted">{v}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
function GenerateModal({
  status,
  onClose,
  onImported,
}: {
  status: AppStatus | null;
  onClose: () => void;
  onImported: () => void;
}) {
  const [params, setParams] = useState({
    count: 20,
    styles: ["neutral", "friendly"],
    domains: ["customer_support"],
    dialect: "emirati",
    length_mix: ["short", "medium", "long"],
    coverage: [] as string[],
    topics: "",
    brand_terms: "",
    batch_name: `batch_${new Date().toISOString().slice(0, 10)}`,
  });
  const [candidates, setCandidates] = useState<GenerateCandidate[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [model, setModel] = useState("");

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const resp = await post<{ model: string; candidates: GenerateCandidate[] }>(
        "/api/scripts/generate",
        params
      );
      setCandidates(resp.candidates);
      setModel(resp.model);
      setSelected(new Set(resp.candidates.map((c, i) => (c.ok ? i : -1)).filter((i) => i >= 0)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const importSelected = async () => {
    if (!candidates) return;
    setBusy(true);
    try {
      const items = [...selected].map((i) => {
        const c = candidates[i].computed;
        return {
          display_text: c.display_text,
          training_text: c.training_text,
          msa_equivalent: c.msa_equivalent,
          dialect: c.dialect,
          style: c.style,
          domain: c.domain,
          tags: c.tags,
          notes: c.note,
        };
      });
      const resp = await post<{ imported: number; skipped: unknown[] }>("/api/scripts/import", {
        items,
        source: "llm",
        generation_batch: params.batch_name,
        generation_model: model,
      });
      onImported();
      onClose();
      alert(`Imported ${resp.imported} scripts (${resp.skipped.length} skipped)`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title={`Generate scripts (${status?.llm_model ?? "LLM"})`} onClose={onClose} wide>
      {!candidates ? (
        <div className="form-grid">
          <label>
            Count
            <input
              type="number"
              className="input"
              min={1}
              max={100}
              value={params.count}
              onChange={(e) => setParams({ ...params, count: Number(e.target.value) })}
            />
          </label>
          <label>
            Dialect
            <select className="input" value={params.dialect} onChange={(e) => setParams({ ...params, dialect: e.target.value })}>
              {(status?.enums.dialects ?? []).map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </label>
          <label className="span2">
            Styles
            <MultiSelect options={status?.enums.styles ?? []} value={params.styles} onChange={(v) => setParams({ ...params, styles: v })} />
          </label>
          <label className="span2">
            Domains
            <MultiSelect options={status?.enums.domains ?? []} value={params.domains} onChange={(v) => setParams({ ...params, domains: v })} />
          </label>
          <label className="span2">
            Length mix
            <MultiSelect options={["short", "medium", "long"]} value={params.length_mix} onChange={(v) => setParams({ ...params, length_mix: v })} />
          </label>
          <label className="span2">
            Special coverage
            <MultiSelect
              options={["numbers", "dates_times", "prices", "id_codes", "code_switch", "brands"]}
              value={params.coverage}
              onChange={(v) => setParams({ ...params, coverage: v })}
            />
          </label>
          <label className="span2">
            Brand terms / allowed product names
            <input className="input" placeholder="e& , du, باقة فليكس, eLife, 5G…" value={params.brand_terms} onChange={(e) => setParams({ ...params, brand_terms: e.target.value })} />
          </label>
          <label className="span2">
            Topic seeds (optional)
            <textarea className="input" rows={2} placeholder="تفعيل باقة جديدة، شكوى فاتورة، استفسار عن التغطية…" value={params.topics} onChange={(e) => setParams({ ...params, topics: e.target.value })} />
          </label>
          <label className="span2">
            Batch name
            <input className="input" value={params.batch_name} onChange={(e) => setParams({ ...params, batch_name: e.target.value })} />
          </label>
          {error && <div className="banner error span2">{error}</div>}
          <div className="span2 row gap">
            <button className="btn accent" onClick={generate} disabled={busy}>
              {busy ? <Spinner label="Generating…" /> : "Generate candidates"}
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="row spread">
            <span className="muted small">
              {selected.size} of {candidates.length} selected · errors are disabled · review warnings before import
            </span>
            <button className="link-btn" onClick={() => setCandidates(null)}>
              ← back to settings
            </button>
          </div>
          <div className="candidate-list">
            {candidates.map((c, i) => (
              <div key={i} className={`candidate ${c.ok ? "" : "error"}`}>
                <label className="row gap">
                  <input
                    type="checkbox"
                    disabled={!c.ok}
                    checked={selected.has(i)}
                    onChange={(e) => {
                      const next = new Set(selected);
                      e.target.checked ? next.add(i) : next.delete(i);
                      setSelected(next);
                    }}
                  />
                  <div className="grow">
                    <div className="arabic" dir="rtl">{c.computed.display_text}</div>
                    {c.computed.training_text !== c.computed.display_text && (
                      <div className="arabic muted small" dir="rtl">{c.computed.training_text}</div>
                    )}
                    <div className="row gap wrap" style={{ marginTop: 4 }}>
                      <Chip tone="accent">{c.computed.style}</Chip>
                      <Chip>{c.computed.domain}</Chip>
                      <Chip>{c.computed.length_bucket}</Chip>
                      {c.computed.tags.map((t) => (
                        <Chip key={t}>{t}</Chip>
                      ))}
                      {c.errors.map((e2, n) => (
                        <Chip key={n} tone="bad">{e2}</Chip>
                      ))}
                      {c.warnings.map((w, n) => (
                        <Chip key={n} tone="warn">{w}</Chip>
                      ))}
                    </div>
                  </div>
                </label>
              </div>
            ))}
          </div>
          {error && <div className="banner error">{error}</div>}
          <div className="row gap" style={{ marginTop: 12 }}>
            <button className="btn accept" onClick={importSelected} disabled={busy || selected.size === 0}>
              Import {selected.size} scripts
            </button>
            <button className="btn ghost" onClick={generate} disabled={busy}>
              ↺ Regenerate
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
function ImportModal({
  status,
  onClose,
  onImported,
}: {
  status: AppStatus | null;
  onClose: () => void;
  onImported: () => void;
}) {
  const [text, setText] = useState("");
  const [style, setStyle] = useState("neutral");
  const [domain, setDomain] = useState("general");
  const [dialect, setDialect] = useState("emirati");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  const doImport = async () => {
    setError("");
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    const items = [];
    for (const line of lines) {
      if (line.startsWith("{")) {
        try {
          const obj = JSON.parse(line);
          items.push({ style, domain, dialect, ...obj });
        } catch {
          setError(`Invalid JSON line: ${line.slice(0, 60)}…`);
          return;
        }
      } else {
        items.push({ display_text: line, style, domain, dialect });
      }
    }
    if (!items.length) return;
    try {
      const resp = await post<{ imported: number; skipped: { errors: string[]; display_text: string }[] }>(
        "/api/scripts/import",
        { items, source: "import" }
      );
      setResult(
        `Imported ${resp.imported}. Skipped ${resp.skipped.length}` +
          (resp.skipped.length ? `: ${resp.skipped.map((s) => s.errors[0]).join(" | ")}` : "")
      );
      onImported();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Modal title="Import scripts" onClose={onClose} wide>
      <p className="muted small">
        One script per line — either plain Arabic text, or a JSON object per line
        (JSONL) with fields <code>display_text</code>, <code>training_text</code>,{" "}
        <code>style</code>, <code>domain</code>, <code>tags</code>…
      </p>
      <div className="row gap">
        <select className="input" value={style} onChange={(e) => setStyle(e.target.value)}>
          {(status?.enums.styles ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={domain} onChange={(e) => setDomain(e.target.value)}>
          {(status?.enums.domains ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={dialect} onChange={(e) => setDialect(e.target.value)}>
          {(status?.enums.dialects ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <textarea
        className="input arabic"
        dir="rtl"
        rows={10}
        style={{ marginTop: 8 }}
        placeholder={"هلا، كيف أقدر أساعدك اليوم؟\nشو تبغي أسويلك؟"}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <div className="banner error">{error}</div>}
      {result && <div className="banner info">{result}</div>}
      <div className="row gap" style={{ marginTop: 12 }}>
        <button className="btn accept" onClick={doImport}>
          Import
        </button>
        <button className="btn ghost" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
function EditModal({
  script,
  styles,
  domains,
  onClose,
  onSaved,
}: {
  script: Script;
  styles: string[];
  domains: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    display_text: script.display_text,
    training_text: script.training_text,
    msa_equivalent: script.msa_equivalent ?? "",
    style: script.style,
    domain: script.domain,
    notes: script.notes,
    status: script.status,
    active: script.active,
  });
  const [error, setError] = useState("");

  const save = async () => {
    try {
      await patch(`/api/scripts/${script.id}`, {
        ...form,
        msa_equivalent: form.msa_equivalent || null,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Modal title={`Edit ${script.script_id}`} onClose={onClose} wide>
      <div className="form-grid">
        <label className="span2">
          Display text (what the speaker reads)
          <textarea className="input arabic" dir="rtl" rows={2} value={form.display_text} onChange={(e) => setForm({ ...form, display_text: e.target.value })} />
        </label>
        <label className="span2">
          Training text (exact verbalization — numbers as words)
          <textarea className="input arabic" dir="rtl" rows={2} value={form.training_text} onChange={(e) => setForm({ ...form, training_text: e.target.value })} />
        </label>
        <label className="span2">
          MSA equivalent (metadata only, optional)
          <textarea className="input arabic" dir="rtl" rows={1} value={form.msa_equivalent} onChange={(e) => setForm({ ...form, msa_equivalent: e.target.value })} />
        </label>
        <label>
          Style
          <select className="input" value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
            {styles.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Domain
          <select className="input" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })}>
            {domains.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
            {["new", "recorded", "done", "flagged", "retired"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
          Active (in recording queue)
        </label>
        <label className="span2">
          Notes / pronunciation hints
          <textarea className="input" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
      </div>
      {error && <div className="banner error">{error}</div>}
      <div className="row gap" style={{ marginTop: 12 }}>
        <button className="btn accept" onClick={save}>
          Save
        </button>
        <button className="btn ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

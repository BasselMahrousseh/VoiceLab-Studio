import { useCallback, useEffect, useState } from "react";
import { get, mediaUrl, post } from "../api";
import QcPanel from "../components/QcPanel";
import { AsrChip, Chip, HumanChip, QcChip, Spinner } from "../components/widgets";
import { AppStatus, Recording } from "../types";

const PAGE = 20;

export default function Review({
  status,
  onChanged,
}: {
  status: AppStatus | null;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<Recording[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [needsReview, setNeedsReview] = useState(true);
  const [humanStatus, setHumanStatus] = useState("");
  const [qcStatus, setQcStatus] = useState("");
  const [asrStatus, setAsrStatus] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (needsReview) params.set("needs_review", "true");
    if (humanStatus) params.set("human_status", humanStatus);
    if (qcStatus) params.set("qc_status", qcStatus);
    if (asrStatus) params.set("asr_status", asrStatus);
    params.set("limit", String(PAGE));
    params.set("offset", String(page * PAGE));
    get<{ total: number; items: Recording[] }>(`/api/recordings?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(e.message));
  }, [needsReview, humanStatus, qcStatus, asrStatus, page]);

  useEffect(load, [load]);

  const update = (updated: Recording) => {
    setItems((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    onChanged();
  };

  return (
    <div className="page">
      <div className="row spread page-head">
        <h1>Review queue</h1>
        <span className="muted small">{total} recordings</span>
      </div>
      {error && <div className="banner error">{error}</div>}
      <div className="row gap filter-bar">
        <label className="check">
          <input type="checkbox" checked={needsReview} onChange={(e) => { setNeedsReview(e.target.checked); setPage(0); }} />
          Needs attention (pending / QC issues / ASR mismatch)
        </label>
        <select className="input" value={humanStatus} onChange={(e) => { setHumanStatus(e.target.value); setPage(0); }}>
          <option value="">Any decision</option>
          {["pending", "accepted", "rejected"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={qcStatus} onChange={(e) => { setQcStatus(e.target.value); setPage(0); }}>
          <option value="">Any QC</option>
          {["passed", "warning", "failed"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="input" value={asrStatus} onChange={(e) => { setAsrStatus(e.target.value); setPage(0); }}>
          <option value="">Any ASR</option>
          {["not_run", "match", "minor_mismatch", "major_mismatch", "error"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="review-list">
        {items.map((r) => (
          <ReviewRow
            key={r.id}
            rec={r}
            open={open === r.id}
            onToggle={() => setOpen(open === r.id ? null : r.id)}
            onUpdate={update}
            asrConfigured={!!status?.asr_configured}
          />
        ))}
        {!items.length && <div className="panel center-panel muted">Nothing to review 🎉</div>}
      </div>
      <div className="row gap pager">
        <button className="btn ghost small" disabled={page === 0} onClick={() => setPage(page - 1)}>
          ← Prev
        </button>
        <span className="muted small">
          {total ? page * PAGE + 1 : 0}–{Math.min((page + 1) * PAGE, total)} of {total}
        </span>
        <button className="btn ghost small" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>
          Next →
        </button>
      </div>
    </div>
  );
}

function ReviewRow({
  rec,
  open,
  onToggle,
  onUpdate,
  asrConfigured,
}: {
  rec: Recording;
  open: boolean;
  onToggle: () => void;
  onUpdate: (r: Recording) => void;
  asrConfigured: boolean;
}) {
  const [finalText, setFinalText] = useState(rec.final_text ?? rec.script?.training_text ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setFinalText(rec.final_text ?? rec.script?.training_text ?? "");
  }, [rec]);

  const act = async (action: "accept" | "reject" | "verify") => {
    setBusy(true);
    setError("");
    try {
      const body =
        action === "accept" ? { final_text: finalText, note } : action === "reject" ? { note } : undefined;
      const updated = await post<Recording>(`/api/recordings/${rec.id}/${action}`, body);
      onUpdate(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`panel review-row ${open ? "open" : ""}`}>
      <div className="row spread clickable" onClick={onToggle}>
        <div className="row gap">
          <span className="mono small">{rec.script?.script_id}</span>
          <Chip>take {rec.take_number}</Chip>
          <span className="muted small">{rec.duration_sec.toFixed(1)}s</span>
        </div>
        <div className="row gap">
          <QcChip status={rec.qc_status} />
          <AsrChip status={rec.asr_status} />
          <HumanChip status={rec.human_status} />
          <span className="muted">{open ? "▾" : "▸"}</span>
        </div>
      </div>
      {open && (
        <div className="review-detail">
          <div className="arabic script-display small-display" dir="rtl">
            {rec.script?.display_text}
          </div>
          {rec.script && rec.script.training_text !== rec.script.display_text && (
            <div className="arabic muted" dir="rtl">
              {rec.script.training_text}
            </div>
          )}
          <audio controls src={mediaUrl(`/api/recordings/${rec.id}/audio`)} className="player" preload="none" />
          <QcPanel rec={rec} />
          <label className="muted small">
            Final training transcript (edit only if the accepted take deviates from the script):
          </label>
          <textarea
            className="input arabic edit-area"
            dir="rtl"
            rows={2}
            value={finalText}
            onChange={(e) => setFinalText(e.target.value)}
          />
          {finalText.trim() !== (rec.script?.training_text ?? "").trim() && (
            <div className="banner warn small">
              Transcript differs from the script — it will be marked <code>text_edited</code>.
            </div>
          )}
          <input
            className="input"
            placeholder="Review note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {error && <div className="banner error">{error}</div>}
          <div className="row gap action-row">
            <button className="btn accept" disabled={busy} onClick={() => act("accept")}>
              ✓ Accept
            </button>
            <button className="btn danger" disabled={busy} onClick={() => act("reject")}>
              ✗ Reject
            </button>
            <button
              className="btn ghost"
              disabled={busy || !asrConfigured}
              onClick={() => act("verify")}
              title={asrConfigured ? "" : "ASR endpoint not configured"}
            >
              🔍 Run ASR check
            </button>
            {busy && <Spinner />}
          </div>
        </div>
      )}
    </div>
  );
}

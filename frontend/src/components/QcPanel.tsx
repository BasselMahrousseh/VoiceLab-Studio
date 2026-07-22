import { Recording } from "../types";
import { AsrChip, QcChip } from "./widgets";
import DiffText from "./DiffText";

const METRIC_LABELS: Record<string, string> = {
  duration_sec: "Duration (s)",
  speech_rms_dbfs: "Speech level (dBFS)",
  peak_dbfs: "Peak (dBFS)",
  lufs: "Loudness (LUFS)",
  snr_db: "SNR (dB)",
  noise_floor_dbfs: "Noise floor (dBFS)",
  leading_silence_sec: "Lead silence (s)",
  trailing_silence_sec: "Trail silence (s)",
  max_internal_silence_sec: "Max pause (s)",
  clip_count: "Clipped samples",
  speech_ratio: "Speech ratio",
  sample_rate: "Sample rate",
};

export default function QcPanel({ rec, compact }: { rec: Recording; compact?: boolean }) {
  return (
    <div className="qc-panel">
      <div className="row gap">
        <QcChip status={rec.qc_status} />
        <AsrChip status={rec.asr_status} />
        {rec.asr_cer != null && (
          <span className="muted small">CER {(rec.asr_cer * 100).toFixed(1)}%</span>
        )}
      </div>
      {rec.qc_issues.length > 0 && (
        <ul className="qc-issues">
          {rec.qc_issues.map((i, n) => (
            <li key={n} className={i.severity}>
              <b>{i.severity === "fail" ? "✗" : "⚠"}</b> {i.message}
            </li>
          ))}
        </ul>
      )}
      {!compact && (
        <div className="metric-grid">
          {Object.entries(METRIC_LABELS).map(([key, label]) =>
            rec.qc_metrics[key] !== undefined ? (
              <div key={key} className="metric">
                <span className="muted small">{label}</span>
                <b>{String(rec.qc_metrics[key])}</b>
              </div>
            ) : null
          )}
        </div>
      )}
      {rec.asr_status !== "not_run" && rec.asr_text != null && (
        <div className="asr-block">
          <div className="muted small">ASR heard:</div>
          <div className="arabic asr-text">{rec.asr_text || "—"}</div>
          {rec.asr_detail?.normalized_ref != null && rec.asr_detail?.normalized_hyp != null && (
            <DiffText
              reference={rec.asr_detail.normalized_ref}
              hypothesis={rec.asr_detail.normalized_hyp}
            />
          )}
        </div>
      )}
      {rec.asr_status === "error" && rec.asr_detail?.error && (
        <div className="banner error small">{rec.asr_detail.error}</div>
      )}
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, upload } from "../api";
import { formatDuration } from "../App";
import {
  KEYBOARD_RECORDING_START_DELAY_MS,
  listInputDevices,
  requestInputDevices,
  StudioRecorder,
  TakeResult,
} from "../audio/recorder";
import LevelMeter from "../components/LevelMeter";
import QcPanel from "../components/QcPanel";
import Waveform from "../components/Waveform";
import { Chip, Modal, Spinner } from "../components/widgets";
import { AppStatus, Dataset, Recording, Script, SessionInfo, Speaker } from "../types";

type Phase = "ready" | "recording" | "processing" | "review";

export default function Studio({
  status,
  onChanged,
}: {
  status: AppStatus | null;
  onChanged: () => void;
}) {
  const [session, setSession] = useState<SessionInfo | null | undefined>(undefined);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState(Number(localStorage.getItem("vl_studio_dataset")) || 0);
  const [script, setScript] = useState<Script | null>(null);
  const [queueRemaining, setQueueRemaining] = useState(0);
  const [phase, setPhase] = useState<Phase>("ready");
  const [take, setTake] = useState<TakeResult | null>(null);
  const [takeUrl, setTakeUrl] = useState("");
  const [rec, setRec] = useState<Recording | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [showTraining, setShowTraining] = useState(true);
  const [editText, setEditText] = useState<string | null>(null);
  const [flagOpen, setFlagOpen] = useState(false);
  const [flagReason, setFlagReason] = useState("");
  const [roomTone, setRoomTone] = useState<string>("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState(localStorage.getItem("vl_device") || "");
  const [autoAsr, setAutoAsr] = useState(localStorage.getItem("vl_auto_asr") !== "0");

  const recorder = useRef<StudioRecorder | null>(null);
  const timerRef = useRef<number>(0);
  const keyboardStartTimerRef = useRef<number | null>(null);
  const phaseRef = useRef<Phase>("ready");
  phaseRef.current = phase;

  // --- session -------------------------------------------------------------
  const loadSession = useCallback(() => {
    get<SessionInfo | null>("/api/sessions/active").then(setSession).catch(() => setSession(null));
  }, []);
  useEffect(loadSession, [loadSession]);
  useEffect(() => {
    get<Dataset[]>("/api/datasets")
      .then((rows) => {
        const eligible = rows.filter((dataset) => dataset.status === "active" && dataset.script_count > 0);
        setDatasets(eligible);
        setDatasetId((current) => {
          if (eligible.some((dataset) => dataset.id === current)) return current;
          return eligible[0]?.id ?? 0;
        });
      })
      .catch((e) => setError(e.message));
  }, []);

  const loadNext = useCallback(
    (excludeId?: number) => {
      if (!datasetId) {
        setScript(null);
        setQueueRemaining(0);
        return;
      }
      const params = new URLSearchParams({ dataset_id: String(datasetId) });
      if (excludeId) params.set("exclude_id", String(excludeId));
      get<Script | null>(`/api/scripts/next?${params}`).then(setScript).catch((e) => setError(e.message));
      get<{ remaining: number }>(`/api/scripts/queue-count?dataset_id=${datasetId}`)
        .then((r) => setQueueRemaining(r.remaining))
        .catch(() => undefined);
    },
    [datasetId]
  );
  useEffect(() => {
    if (session) loadNext();
  }, [session, loadNext]);

  useEffect(() => () => recorder.current?.close(), []);

  useEffect(() => {
    let cancelled = false;
    const refreshDevices = async () => {
      try {
        const devs = await requestInputDevices();
        if (!cancelled) setDevices(devs);
      } catch {
        const devs = await listInputDevices();
        if (!cancelled) setDevices(devs);
      }
    };
    void refreshDevices();
    navigator.mediaDevices?.addEventListener("devicechange", refreshDevices);
    return () => {
      cancelled = true;
      navigator.mediaDevices?.removeEventListener("devicechange", refreshDevices);
    };
  }, []);

  // --- recording -----------------------------------------------------------
  const ensureRecorder = useCallback(async (): Promise<StudioRecorder> => {
    if (!recorder.current || !recorder.current.ready) {
      const r = new StudioRecorder();
      await r.init(deviceId || undefined);
      recorder.current = r;
      const devs = await listInputDevices();
      setDevices(devs);
    }
    return recorder.current;
  }, [deviceId]);

  const startRecording = useCallback(async () => {
    setError("");
    try {
      const r = await ensureRecorder();
      setTake(null);
      setRec(null);
      setEditText(null);
      if (takeUrl) URL.revokeObjectURL(takeUrl);
      setTakeUrl("");
      r.start();
      setPhase("recording");
      const started = performance.now();
      timerRef.current = window.setInterval(() => {
        const sec = (performance.now() - started) / 1000;
        setElapsed(sec);
        if (sec >= 24.5) void stopRecording(); // hard ceiling guard
      }, 100);
    } catch (e) {
      setError(`Microphone error: ${(e as Error).message}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ensureRecorder, takeUrl, script, session]);

  useEffect(
    () => () => {
      if (keyboardStartTimerRef.current !== null) {
        window.clearTimeout(keyboardStartTimerRef.current);
      }
    },
    []
  );

  const stopRecording = useCallback(async () => {
    if (!recorder.current || phaseRef.current !== "recording") return;
    clearInterval(timerRef.current);
    setPhase("processing");
    try {
      const result = await recorder.current.stop();
      setTake(result);
      setTakeUrl(URL.createObjectURL(result.blob));
      if (!script || !session) return;
      const uploaded = await upload<Recording>("/api/recordings", result.blob, `${script.script_id}.wav`, {
        script_pk: script.id,
        session_id: session.id,
      });
      setRec(uploaded);
      setPhase("review");
      loadSession();
      if (autoAsr && status?.asr_configured && uploaded.qc_status !== "failed") {
        setVerifying(true);
        post<Recording>(`/api/recordings/${uploaded.id}/verify`)
          .then(setRec)
          .catch((e) => setError(`ASR verify failed: ${e.message}`))
          .finally(() => setVerifying(false));
      }
    } catch (e) {
      setError((e as Error).message);
      setPhase("ready");
    }
  }, [script, session, autoAsr, status, loadSession]);

  const accept = useCallback(async (force = false) => {
    if (!rec) return;
    try {
      await post<Recording>(`/api/recordings/${rec.id}/accept`, {
        final_text: editText !== null ? editText : undefined,
        force,
      });
      setPhase("ready");
      setTake(null);
      setRec(null);
      setEditText(null);
      loadNext();
      loadSession();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [rec, editText, loadNext, loadSession, onChanged]);

  const rerecord = useCallback(async () => {
    if (rec) {
      await post(`/api/recordings/${rec.id}/reject`, { note: "re-recorded" }).catch(() => undefined);
      loadSession();
    }
    setPhase("ready");
    setTake(null);
    setRec(null);
    setEditText(null);
  }, [rec, loadSession]);

  const skip = useCallback(() => {
    setPhase("ready");
    setTake(null);
    setRec(null);
    setEditText(null);
    if (script) loadNext(script.id);
  }, [script, loadNext]);

  // --- keyboard shortcuts ----------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || flagOpen) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (phaseRef.current === "ready") {
          if (e.repeat || keyboardStartTimerRef.current !== null) return;
          keyboardStartTimerRef.current = window.setTimeout(() => {
            keyboardStartTimerRef.current = null;
            if (phaseRef.current === "ready") void startRecording();
          }, KEYBOARD_RECORDING_START_DELAY_MS);
        } else if (phaseRef.current === "recording") {
          void stopRecording();
        }
      } else if (
        e.key === "Enter" &&
        phaseRef.current === "review" &&
        rec &&
        rec.qc_status !== "failed"
      ) {
        e.preventDefault();
        void accept();
      } else if ((e.key === "r" || e.key === "R") && phaseRef.current === "review") {
        void rerecord();
      } else if ((e.key === "s" || e.key === "S") && phaseRef.current !== "recording") {
        skip();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [startRecording, stopRecording, accept, rerecord, skip, rec, flagOpen]);

  const roomToneCheck = useCallback(async () => {
    if (!session) return;
    setRoomTone("Recording 3s of room tone — stay silent…");
    try {
      const r = await ensureRecorder();
      r.start();
      await new Promise((res) => setTimeout(res, 3000));
      const result = await r.stop();
      const resp = await upload<{ message: string; status: string }>(
        `/api/sessions/${session.id}/room-tone`,
        result.blob,
        "room_tone.wav"
      );
      setRoomTone(resp.message);
      loadSession();
    } catch (e) {
      setRoomTone(`Room tone check failed: ${(e as Error).message}`);
    }
  }, [session, ensureRecorder, loadSession]);

  // --- render ----------------------------------------------------------------
  if (session === undefined) return <Spinner label="Loading session…" />;
  if (!session) return <SessionStart onStarted={(s) => { setSession(s); onChanged(); }} />;

  return (
    <div className="studio">
      <div className="session-bar">
        <div>
          <b>{session.speaker?.display_name || session.speaker?.speaker_key}</b>
          <span className="muted"> · session #{session.id}</span>
          {session.room_tone_status && (
            <Chip tone={session.room_tone_status === "ok" ? "ok" : "warn"}>
              room {session.room_tone_dbfs} dBFS
            </Chip>
          )}
        </div>
        <div className="row gap">
          <select
            className="input small-select"
            value={datasetId}
            onChange={(event) => {
              const next = Number(event.target.value);
              setDatasetId(next);
              localStorage.setItem("vl_studio_dataset", String(next));
            }}
          >
            {!datasets.length && <option value={0}>No populated dataset</option>}
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>{dataset.name}</option>
            ))}
          </select>
          <span className="muted small">
            {session.accepted_count}/{session.recording_count} accepted · {queueRemaining} in queue
          </span>
          <button className="btn ghost small" onClick={roomToneCheck} disabled={phase === "recording"}>
            Room tone check
          </button>
          <button
            className="btn ghost small"
            onClick={async () => {
              await post(`/api/sessions/${session.id}/end`);
              setSession(null);
              onChanged();
            }}
          >
            End session
          </button>
        </div>
      </div>
      {roomTone && <div className="banner info">{roomTone}</div>}
      {error && <div className="banner error">{error}</div>}

      {!script ? (
        <div className="panel center-panel">
          <h2>🎉 Queue is empty</h2>
          <p className="muted">All active scripts are recorded. Add or generate more from the Datasets page.</p>
        </div>
      ) : (
        <>
          <div className="panel script-panel">
            <div className="row spread">
              <div className="row gap">
                <Chip>{script.script_id}</Chip>
                <Chip tone="accent">{script.language}</Chip>
                <Chip tone="accent">{script.style}</Chip>
                <Chip>{script.domain}</Chip>
                <Chip>{script.dialect}</Chip>
                <Chip>{script.length_bucket}</Chip>
                {script.take_count > 0 && <Chip tone="warn">take {script.take_count + 1}</Chip>}
              </div>
              <button className="btn ghost small" onClick={() => setFlagOpen(true)}>
                ⚑ Flag script
              </button>
            </div>
            <div className="arabic script-display" dir="auto">
              {script.display_text}
            </div>
            {script.training_text !== script.display_text && (
              <div className="training-line">
                <button className="link-btn" onClick={() => setShowTraining(!showTraining)}>
                  {showTraining ? "▾" : "▸"} exact reading (training text)
                </button>
                {showTraining && (
                  <div className="arabic training-text" dir="auto">
                    {script.training_text}
                  </div>
                )}
              </div>
            )}
            {script.notes && <div className="muted small note-line">📝 {script.notes}</div>}
          </div>

          <div className="panel recorder-panel">
            <div className="row spread">
              <div className="row gap">
                {phase !== "recording" ? (
                  <button
                    className="btn record"
                    onClick={startRecording}
                    disabled={phase === "processing"}
                  >
                    ● Record <kbd>Space</kbd>
                  </button>
                ) : (
                  <button className="btn stop" onClick={stopRecording}>
                    ■ Stop <kbd>Space</kbd>
                  </button>
                )}
                <span className={`timer ${phase === "recording" ? "live" : ""}`}>
                  {formatTimer(phase === "recording" ? elapsed : take?.durationSec ?? 0)}
                </span>
                <span className="muted small">target 3–12 s</span>
              </div>
              <div className="row gap">
                <select
                  className="input small-select"
                  value={deviceId}
                  onChange={async (e) => {
                    setDeviceId(e.target.value);
                    localStorage.setItem("vl_device", e.target.value);
                    recorder.current?.close();
                    recorder.current = null;
                  }}
                  title="Input device"
                >
                  <option value="">Default microphone</option>
                  {devices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || d.deviceId.slice(0, 12)}
                    </option>
                  ))}
                </select>
                <label className="check small muted">
                  <input
                    type="checkbox"
                    checked={autoAsr}
                    onChange={(e) => {
                      setAutoAsr(e.target.checked);
                      localStorage.setItem("vl_auto_asr", e.target.checked ? "1" : "0");
                    }}
                    disabled={!status?.asr_configured}
                  />
                  auto ASR check
                </label>
              </div>
            </div>
            <LevelMeter recorder={recorder.current} active={phase === "recording"} />
            {phase === "processing" && <Spinner label="Uploading & running QC…" />}
          </div>

          {phase === "review" && take && rec && (
            <div className="panel review-panel">
              <Waveform samples={take.samples} />
              <div className="row gap">
                <audio controls src={takeUrl} className="player" />
                {verifying && <Spinner label="ASR verifying…" />}
              </div>
              <QcPanel rec={rec} />
              {rec.forced_save && (
                <div className="banner warn small">
                  This take was saved with a human override despite failed automatic QC.
                </div>
              )}
              <div className="edit-block">
                <button
                  className="link-btn"
                  onClick={() => setEditText(editText === null ? rec.script?.training_text ?? script.training_text : null)}
                >
                  {editText === null ? "✎ Speaker said something different? Edit transcript" : "✕ discard transcript edit"}
                </button>
                {editText !== null && (
                  <textarea
                    className="input arabic edit-area"
                    dir="auto"
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    rows={2}
                  />
                )}
              </div>
              <div className="row gap action-row">
                {rec.qc_status === "failed" ? (
                  <button className="btn danger" onClick={() => accept(true)}>
                    ✓ Save anyway {editText !== null && "with edit"}
                  </button>
                ) : (
                  <button className="btn accept" onClick={() => accept(false)}>
                    ✓ Accept {editText !== null && "with edit"} <kbd>Enter</kbd>
                  </button>
                )}
                <button className="btn" onClick={rerecord}>
                  ↺ Re-record <kbd>R</kbd>
                </button>
                <button className="btn ghost" onClick={skip}>
                  Skip <kbd>S</kbd>
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {flagOpen && script && (
        <Modal title={`Flag ${script.script_id}`} onClose={() => setFlagOpen(false)}>
          <p className="muted small">
            Flag removes this script from the queue (bad text, wrong dialect, unreadable…).
          </p>
          <textarea
            className="input"
            rows={3}
            placeholder="Reason"
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
          />
          <div className="row gap" style={{ marginTop: 12 }}>
            <button
              className="btn danger"
              onClick={async () => {
                await post(`/api/scripts/${script.id}/flag`, { reason: flagReason });
                setFlagOpen(false);
                setFlagReason("");
                skip();
              }}
            >
              Flag & next
            </button>
            <button className="btn ghost" onClick={() => setFlagOpen(false)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function formatTimer(sec: number): string {
  const m = Math.floor(sec / 60);
  return `${m}:${(sec % 60).toFixed(1).padStart(4, "0")}`;
}

// ---------------------------------------------------------------------------
function SessionStart({ onStarted }: { onStarted: (s: SessionInfo) => void }) {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [speakerId, setSpeakerId] = useState<number>(0);
  const [newKey, setNewKey] = useState("");
  const [newName, setNewName] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    get<Speaker[]>("/api/speakers").then((s) => {
      setSpeakers(s);
      if (s.length) setSpeakerId(s[0].id);
    });
  }, []);

  const start = async () => {
    try {
      let id = speakerId;
      if (showNew && newKey) {
        const created = await post<Speaker>("/api/speakers", {
          speaker_key: newKey,
          display_name: newName,
        });
        id = created.id;
      }
      const session = await post<SessionInfo>("/api/sessions/start", {
        speaker_id: id,
        device_info: { userAgent: navigator.userAgent },
      });
      onStarted(session);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="panel center-panel session-start">
      <h2>Start a recording session</h2>
      <p className="muted">
        Sessions group takes for tracking and device consistency. Run a room-tone check after
        starting.
      </p>
      {error && <div className="banner error">{error}</div>}
      {!showNew ? (
        <div className="row gap">
          <select className="input" value={speakerId} onChange={(e) => setSpeakerId(Number(e.target.value))}>
            {speakers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.display_name || s.speaker_key}
              </option>
            ))}
          </select>
          <button className="link-btn" onClick={() => setShowNew(true)}>
            + new speaker
          </button>
        </div>
      ) : (
        <div className="row gap">
          <input className="input" placeholder="speaker_002" value={newKey} onChange={(e) => setNewKey(e.target.value)} />
          <input className="input" placeholder="Display name" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button className="link-btn" onClick={() => setShowNew(false)}>
            existing
          </button>
        </div>
      )}
      <button className="btn accept big" onClick={start}>
        ▶ Start session
      </button>
    </div>
  );
}

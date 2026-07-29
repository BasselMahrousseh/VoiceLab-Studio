import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, post, upload } from "../api";
import { useAuth } from "../auth";
import { listInputDevices, StudioRecorder, TakeResult } from "../audio/recorder";
import Logo from "../components/Logo";
import LevelMeter from "../components/LevelMeter";
import Waveform from "../components/Waveform";
import { Chip, Spinner } from "../components/widgets";
import { AppStatus, QcIssue, Recording, RecorderContext, Script } from "../types";

type Phase = "ready" | "recording" | "processing" | "review" | "transition";
type ConnectionState = "checking" | "connected" | "offline";
type WorkflowStepState = "pending" | "active" | "success" | "error";

interface WorkflowStep {
  key: string;
  label: string;
  state: WorkflowStepState;
  detail?: string;
}

interface SessionStats {
  recorded: number;
  accepted: number;
  restarted: number;
  skipped: number;
}

const DEFAULT_SECONDS_PER_SENTENCE = 12;

export default function Recorder() {
  const { user, logout } = useAuth();
  const [ctx, setCtx] = useState<RecorderContext | null | undefined>(undefined);
  const [script, setScript] = useState<Script | null>(null);
  const [phase, setPhase] = useState<Phase>("ready");
  const [take, setTake] = useState<TakeResult | null>(null);
  const [takeUrl, setTakeUrl] = useState("");
  const [rec, setRec] = useState<Recording | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [roomToneMessage, setRoomToneMessage] = useState<string>("");
  const [roomToneBusy, setRoomToneBusy] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState(localStorage.getItem("lahja_device") || "");
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [workflowTitle, setWorkflowTitle] = useState("");
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>([]);
  const [sessionStats, setSessionStats] = useState<SessionStats>({
    recorded: 0,
    accepted: 0,
    restarted: 0,
    skipped: 0,
  });

  const recorder = useRef<StudioRecorder | null>(null);
  const timerRef = useRef<number>(0);
  const phaseRef = useRef<Phase>("ready");
  const sessionStartedAtRef = useRef<number>(Date.now());
  phaseRef.current = phase;

  const loadContext = useCallback(() => {
    get<RecorderContext>("/api/recorder/context")
      .then((c) => {
        setCtx(c);
        setScript(c.next_script);
        setConnection("connected");
        setError("");
      })
      .catch((e) => {
        setError(e.message);
        setCtx(null);
        setConnection("offline");
      });
  }, []);
  useEffect(loadContext, [loadContext]);

  useEffect(() => () => recorder.current?.close(), []);

  useEffect(() => {
    setConnection("checking");
    get<AppStatus>("/api/status")
      .then(() => setConnection("connected"))
      .catch(() => setConnection("offline"));
    const id = window.setInterval(() => {
      get<AppStatus>("/api/status")
        .then(() => setConnection("connected"))
        .catch(() => setConnection("offline"));
    }, 15000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (ctx?.session_id) sessionStartedAtRef.current = Date.now();
  }, [ctx?.session_id]);

  const ensureRecorder = useCallback(async (): Promise<StudioRecorder> => {
    if (!recorder.current || !recorder.current.ready) {
      const r = new StudioRecorder();
      await r.init(deviceId || undefined);
      recorder.current = r;
      setDevices(await listInputDevices());
    }
    return recorder.current;
  }, [deviceId]);

  const roomToneCheck = useCallback(async () => {
    if (!ctx?.session_id) return;
    if (phaseRef.current !== "ready") return;
    if (roomToneBusy) return;

    setRoomToneBusy(true);
    setRoomToneMessage("Recording 3s of room tone — stay silent…");
    try {
      const r = await ensureRecorder();
      r.start();
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
      const result = await r.stop();

      const resp = await upload<{ message: string; status: string; room_tone_dbfs: number }>(
        `/api/sessions/${ctx.session_id}/room-tone`,
        result.blob,
        "room_tone.wav"
      );
      setRoomToneMessage(resp.message);
      await loadContext();
    } catch (e) {
      setRoomToneMessage(`Room tone check failed: ${(e as Error).message}`);
    } finally {
      setRoomToneBusy(false);
    }
  }, [ctx?.session_id, ensureRecorder, loadContext, roomToneBusy]);

  const resetTake = useCallback(() => {
    setTake(null);
    setRec(null);
    if (takeUrl) URL.revokeObjectURL(takeUrl);
    setTakeUrl("");
  }, [takeUrl]);

  const updateWorkflowStep = useCallback(
    (key: string, patch: Partial<WorkflowStep>) => {
      setWorkflowSteps((steps) =>
        steps.map((step) => (step.key === key ? { ...step, ...patch } : step))
      );
    },
    []
  );

  const beginWorkflow = useCallback((title: string, steps: WorkflowStep[]) => {
    setWorkflowTitle(title);
    setWorkflowSteps(steps);
  }, []);

  const uploadCurrentTake = useCallback(
    async (result: TakeResult) => {
      if (!script || !ctx?.session_id) throw new Error("No active script or session available.");
      beginWorkflow("Saving your recording", [
        { key: "upload", label: "Uploading recording...", state: "active" },
        { key: "quality", label: "Running quality checks...", state: "pending" },
      ]);
      const uploaded = await upload<Recording>("/api/recordings", result.blob, `${script.script_id}.wav`, {
        script_pk: script.id,
        session_id: ctx.session_id,
      });
      updateWorkflowStep("upload", { state: "success", label: "Upload completed" });
      updateWorkflowStep("quality", { state: "active" });
      updateWorkflowStep("quality", { state: "success", label: "Recording saved successfully" });
      setRec(uploaded);
      setSessionStats((stats) => ({ ...stats, recorded: stats.recorded + 1 }));
      setPhase("review");
      return uploaded;
    },
    [beginWorkflow, ctx, script, updateWorkflowStep]
  );

  const startRecording = useCallback(async () => {
    setError("");
    try {
      const r = await ensureRecorder();
      resetTake();
      r.start();
      setPhase("recording");
      const started = performance.now();
      timerRef.current = window.setInterval(() => {
        const sec = (performance.now() - started) / 1000;
        setElapsed(sec);
        if (sec >= 24.5) void stopRecording();
      }, 100);
    } catch (e) {
      setError(`Microphone error: ${(e as Error).message}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ensureRecorder, resetTake]);

  const stopRecording = useCallback(async () => {
    if (!recorder.current || phaseRef.current !== "recording") return;
    clearInterval(timerRef.current);
    setPhase("processing");
    try {
      const result = await recorder.current.stop();
      setTake(result);
      setTakeUrl(URL.createObjectURL(result.blob));
      await uploadCurrentTake(result);
    } catch (e) {
      const message = (e as Error).message;
      setError(message);
      setWorkflowTitle("Save failed");
      setWorkflowSteps([
        { key: "upload", label: "Upload failed", state: "error", detail: message },
        { key: "quality", label: "Retry to save this recording", state: "pending" },
      ]);
      setPhase("processing");
    }
  }, [uploadCurrentTake]);

  const save = useCallback(async (force = false) => {
    if (!rec) return;
    try {
      setError("");
      setPhase("transition");
      beginWorkflow("Saving and loading next sentence", [
        { key: "save", label: "Saving recording...", state: "active" },
        { key: "next", label: "Loading next sentence...", state: "pending" },
      ]);
      await post(`/api/recordings/${rec.id}/accept`, { force });
      updateWorkflowStep("save", { state: "success", label: "Recording saved" });
      setSessionStats((stats) => ({ ...stats, accepted: stats.accepted + 1 }));
      updateWorkflowStep("next", { state: "active" });
      resetTake();
      setElapsed(0);
      await new Promise((resolve) => window.setTimeout(resolve, 450));
      await new Promise<void>((resolve, reject) => {
        get<RecorderContext>("/api/recorder/context")
          .then((nextCtx) => {
            setCtx(nextCtx);
            setScript(nextCtx.next_script);
            setConnection("connected");
            updateWorkflowStep("next", { state: "success", label: "Next sentence ready" });
            resolve();
          })
          .catch(reject);
      });
      await new Promise((resolve) => window.setTimeout(resolve, 220));
      setWorkflowTitle("");
      setWorkflowSteps([]);
      setPhase("ready");
    } catch (e) {
      const message = (e as Error).message;
      setError(message);
      updateWorkflowStep("save", { state: "error", label: "Save failed", detail: message });
      setPhase("review");
    }
  }, [beginWorkflow, rec, resetTake, updateWorkflowStep]);

  const restart = useCallback(async () => {
    if (rec) {
      await post(`/api/recordings/${rec.id}/reject`, { note: "re-recorded" }).catch(() => undefined);
    }
    setSessionStats((stats) => ({ ...stats, restarted: stats.restarted + 1 }));
    resetTake();
    setWorkflowTitle("");
    setWorkflowSteps([]);
    setPhase("ready");
    setElapsed(0);
  }, [rec, resetTake]);

  const skip = useCallback(async () => {
    if (!script) return;
    setError("");
    if (rec) {
      await post(`/api/recordings/${rec.id}/reject`, { note: "skipped by recorder" }).catch(
        () => undefined
      );
    }
    resetTake();
    setPhase("transition");
    setElapsed(0);
    try {
      beginWorkflow("Skipping sentence", [
        { key: "skip", label: "Marking this sentence as skipped...", state: "active" },
        { key: "next", label: "Loading next sentence...", state: "pending" },
      ]);
      setSessionStats((stats) => ({ ...stats, skipped: stats.skipped + 1 }));
      updateWorkflowStep("skip", { state: "success", label: "Sentence skipped" });
      updateWorkflowStep("next", { state: "active" });
      const next = await get<Script | null>(`/api/recorder/next?exclude_id=${script.id}`);
      if (next) {
        setScript(next);
        updateWorkflowStep("next", { state: "success", label: "Next sentence ready" });
        await new Promise((resolve) => window.setTimeout(resolve, 220));
        setWorkflowTitle("");
        setWorkflowSteps([]);
        setPhase("ready");
      } else {
        setScript(script);
        setError("There are no other unrecorded sentences to skip to.");
        updateWorkflowStep("next", {
          state: "error",
          label: "No alternate sentence available",
          detail: "There are no other unrecorded sentences to skip to.",
        });
        setPhase("ready");
      }
    } catch (e) {
      const message = (e as Error).message;
      setError(message);
      updateWorkflowStep("next", { state: "error", label: "Could not load the next sentence", detail: message });
      setPhase("ready");
    }
  }, [beginWorkflow, script, rec, resetTake, updateWorkflowStep]);

  // keyboard: Space = record/stop, Enter = save, R = restart, S = skip
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (phaseRef.current === "ready") void startRecording();
        else if (phaseRef.current === "recording") void stopRecording();
      } else if (e.key === "Enter" && phaseRef.current === "review" && rec?.qc_status !== "failed") {
        e.preventDefault();
        void save();
      } else if ((e.key === "r" || e.key === "R") && phaseRef.current === "review") {
        void restart();
      } else if ((e.key === "s" || e.key === "S") && phaseRef.current !== "recording") {
        void skip();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [startRecording, stopRecording, save, restart, skip, rec]);

  const progress = ctx?.progress;
  const pct = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const qcFailed = rec?.qc_status === "failed";
  const qcWarn = rec?.qc_status === "warning";
  const currentSentence = progress?.total ? Math.min(progress.done + (script ? 1 : 0), progress.total) : 0;
  const elapsedSessionSec = Math.max(0, Math.round((Date.now() - sessionStartedAtRef.current) / 1000));
  const averageSecondsPerSentence = useMemo(() => {
    if (sessionStats.accepted > 0) return elapsedSessionSec / sessionStats.accepted;
    if (ctx?.dataset?.accepted_count) {
      return ctx.dataset.accepted_duration_sec / ctx.dataset.accepted_count;
    }
    return DEFAULT_SECONDS_PER_SENTENCE;
  }, [ctx?.dataset?.accepted_count, ctx?.dataset?.accepted_duration_sec, elapsedSessionSec, sessionStats.accepted]);
  const estimatedRemainingSec = Math.max(0, Math.round((progress?.remaining ?? 0) * averageSecondsPerSentence));
  const qualitySummary = rec ? summarizeQuality(rec) : null;
  const completionStats = progress && progress.total > 0 && !script;

  if (ctx === undefined) return <div className="app-loading"><Spinner label="Loading your session…" /></div>;

  return (
    <div className="recorder-shell">
      <header className="recorder-top">
        <div className="row gap">
          <Logo height={40} />
        </div>
        <div className="row gap">
          <ConnectionPill state={connection} />
          {ctx?.room_tone_status && (
            <Chip tone={ctx.room_tone_status === "ok" ? "ok" : "warn"}>
              room {ctx.room_tone_dbfs != null ? ctx.room_tone_dbfs.toFixed(0) : "?"} dBFS
            </Chip>
          )}
          <button
            className="btn ghost small"
            onClick={() => void roomToneCheck()}
            disabled={!ctx?.session_id || roomToneBusy || phase !== "ready"}
            title="3s silence capture to estimate room tone noise floor"
          >
            Room tone check
          </button>
          <span className="muted small">{user?.display_name || user?.username}</span>
          <button className="btn ghost small" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {progress && (
        <div className="panel recorder-progress fade-in">
          <div className="row spread recorder-progress-head">
            <div>
              <div className="muted small">Active dataset</div>
              <h2>{ctx?.dataset?.name || "Assigned dataset"}</h2>
            </div>
            <div className="recorder-progress-stats">
              <span className="chip accent">{pct}% completed</span>
              <span className="muted small">{formatRemainingTime(estimatedRemainingSec)} remaining</span>
            </div>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="recorder-progress-body">
            <div className="recorder-progress-main">
              <div className="recorder-progress-title">
                Sentence {currentSentence || progress.total} of {progress.total}
              </div>
              <div className="recorder-progress-grid">
                <div className="progress-stat">
                  <span className="progress-stat-label">Recorded</span>
                  <strong>{progress.done}</strong>
                </div>
                <div className="progress-stat">
                  <span className="progress-stat-label">Remaining</span>
                  <strong>{progress.remaining}</strong>
                </div>
                <div className="progress-stat">
                  <span className="progress-stat-label">Completed</span>
                  <strong>{pct}%</strong>
                </div>
                <div className="progress-stat">
                  <span className="progress-stat-label">Estimated time left</span>
                  <strong>{formatRemainingTime(estimatedRemainingSec)}</strong>
                </div>
              </div>
            </div>
            <SessionStatsCard stats={sessionStats} durationSec={elapsedSessionSec} />
          </div>
        </div>
      )}

      <main className="recorder-main">
        {roomToneMessage && <div className="banner info">{roomToneMessage}</div>}
        {error && <div className="banner error">{error}</div>}

        {ctx?.dataset?.instructions && (
          <div className="guide-box">
            <button className="link-btn" onClick={() => setShowGuide(!showGuide)}>
              {showGuide ? "▾" : "▸"} Recording instructions
            </button>
            {showGuide && <pre className="guide-text">{ctx.dataset.instructions}</pre>}
          </div>
        )}

        {!script && progress?.total === 0 ? (
          <div className="panel done-panel fade-in">
            <div className="done-emoji">📭</div>
            <h2>No scripts are available yet</h2>
            <p className="muted">
              Your account is assigned to <b>{ctx?.dataset?.name || "a dataset"}</b>, but it has no
              active recording scripts. Please contact the project administrator.
            </p>
            <button className="btn ghost" onClick={loadContext}>
              Check again
            </button>
          </div>
        ) : completionStats ? (
          <div className="panel done-panel fade-in">
            <div className="done-emoji">🎉</div>
            <h2>Great work!</h2>
            <p className="muted">You completed this dataset.</p>
            <div className="completion-stats">
              <div className="completion-stat">
                <span className="muted small">Progress</span>
                <strong>{progress.done} / {progress.total} recorded</strong>
              </div>
              <div className="completion-stat">
                <span className="muted small">Recording time</span>
                <strong>{formatRemainingTime(elapsedSessionSec)}</strong>
              </div>
              <div className="completion-stat">
                <span className="muted small">Accepted</span>
                <strong>{sessionStats.accepted || progress.done}</strong>
              </div>
            </div>
            <p className="muted">Thank you!</p>
          </div>
        ) : (
          <>
            <div className="panel prompt-panel fade-in" key={script!.id}>
              <div className="row spread">
                <div className="prompt-label muted small">Please read aloud</div>
                <span className="chip accent">{script!.language}</span>
              </div>
              <div className="arabic prompt-text" dir="auto">
                {script!.display_text}
              </div>
              {script!.notes && <div className="muted small note-line">📝 {script!.notes}</div>}
            </div>

            <div className="panel record-panel">
              {(phase === "ready" || phase === "recording" || phase === "processing") && (
                <>
                  <div className="record-controls">
                    {phase !== "recording" ? (
                      <button
                        className="btn record huge"
                        onClick={startRecording}
                        disabled={phase === "processing"}
                      >
                        ● Record
                      </button>
                    ) : (
                      <button className="btn stop huge" onClick={stopRecording}>
                        ■ Stop
                      </button>
                    )}
                    <div className={`recording-status-card ${phase === "recording" ? "live" : ""}`}>
                      <span className="recording-status-label">
                        {phase === "recording" ? "Recording live" : phase === "processing" ? "Saving recording" : "Ready to record"}
                      </span>
                      <span className={`timer big ${phase === "recording" ? "live" : ""}`}>
                        {formatTimer(elapsed)}
                      </span>
                      <span className="muted small">
                        Press <kbd>Space</kbd> to {phase === "recording" ? "stop" : "start"}
                      </span>
                    </div>
                    {phase === "ready" && (
                      <button className="btn ghost" onClick={skip}>
                        Skip sentence <kbd>S</kbd>
                      </button>
                    )}
                  </div>
                  <LevelMeter recorder={recorder.current} active={phase === "recording"} />
                  {phase === "processing" && (
                    <WorkflowCard
                      title={workflowTitle || "Saving your recording"}
                      steps={workflowSteps}
                      actionRow={
                        !rec ? (
                          <div className="row gap wrap">
                            <button className="btn accent" onClick={() => take && void uploadCurrentTake(take)}>
                              Retry upload
                            </button>
                            <button className="btn ghost" onClick={restart}>
                              Restart
                            </button>
                          </div>
                        ) : null
                      }
                    />
                  )}
                </>
              )}

              {phase === "review" && take && rec && (
                <div className="review-block fade-in">
                  <WorkflowCard title="Recording saved" steps={workflowSteps} compact />
                  <Waveform samples={take.samples} />
                  <audio controls src={takeUrl} className="player" />
                  {qualitySummary && (
                    <QualityCard
                      summary={qualitySummary}
                      qcIssues={rec.qc_issues}
                      warning={qcWarn}
                      failed={qcFailed}
                    />
                  )}
                  <div className="row gap action-row">
                    {qcFailed ? (
                      <button className="btn danger big" onClick={() => save(true)}>
                        ✓ Save anyway &amp; next
                      </button>
                    ) : (
                      <button className="btn accept big" onClick={() => save(false)}>
                        ✓ Save &amp; next <kbd>Enter</kbd>
                      </button>
                    )}
                    <button className="btn big" onClick={restart}>
                      ↺ Restart <kbd>R</kbd>
                    </button>
                    <button className="btn ghost big" onClick={skip}>
                      Skip <kbd>S</kbd>
                    </button>
                  </div>
                </div>
              )}

              {phase === "transition" && (
                <WorkflowCard title={workflowTitle} steps={workflowSteps} />
              )}
            </div>

            <div className="recorder-footer">
              <div className="mic-row">
                <label className="muted small">
                  Microphone{" "}
                  <select
                    className="input small-select"
                    value={deviceId}
                    onChange={async (e) => {
                      setDeviceId(e.target.value);
                      localStorage.setItem("lahja_device", e.target.value);
                      recorder.current?.close();
                      recorder.current = null;
                    }}
                  >
                    <option value="">Default microphone</option>
                    {devices.map((d) => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label || d.deviceId.slice(0, 12)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <ShortcutBar />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function formatTimer(sec: number): string {
  const m = Math.floor(sec / 60);
  return `${m}:${(sec % 60).toFixed(1).padStart(4, "0")}`;
}

function formatRemainingTime(sec: number): string {
  if (sec < 60) return `${Math.max(1, sec)} sec`;
  const min = Math.round(sec / 60);
  return `${min} min`;
}

function ConnectionPill({ state }: { state: ConnectionState }) {
  const label = state === "connected" ? "Connected" : state === "offline" ? "Offline" : "Checking";
  return <span className={`chip status-pill ${state}`}>{label}</span>;
}

function WorkflowCard({
  title,
  steps,
  compact,
  actionRow,
}: {
  title: string;
  steps: WorkflowStep[];
  compact?: boolean;
  actionRow?: ReactNode;
}) {
  return (
    <div className={`workflow-card ${compact ? "compact" : ""}`}>
      <div className="workflow-title">{title}</div>
      <div className="workflow-steps">
        {steps.map((step) => (
          <div key={step.key} className={`workflow-step ${step.state}`}>
            <span className="workflow-icon">{workflowIcon(step.state)}</span>
            <div>
              <div className="workflow-label">{step.label}</div>
              {step.detail && <div className="workflow-detail muted small">{step.detail}</div>}
            </div>
          </div>
        ))}
      </div>
      {actionRow}
    </div>
  );
}

function SessionStatsCard({ stats, durationSec }: { stats: SessionStats; durationSec: number }) {
  return (
    <section className="session-stats-card">
      <div className="session-stats-head">Today&apos;s Session</div>
      <div className="session-stats-grid">
        <div><span className="muted small">Recorded</span><strong>{stats.recorded}</strong></div>
        <div><span className="muted small">Accepted</span><strong>{stats.accepted}</strong></div>
        <div><span className="muted small">Restarted</span><strong>{stats.restarted}</strong></div>
        <div><span className="muted small">Skipped</span><strong>{stats.skipped}</strong></div>
        <div><span className="muted small">Duration</span><strong>{formatRemainingTime(durationSec)}</strong></div>
      </div>
    </section>
  );
}

function ShortcutBar() {
  return (
    <div className="shortcut-bar">
      <span><kbd>Space</kbd> Record</span>
      <span><kbd>Enter</kbd> Save</span>
      <span><kbd>R</kbd> Restart</span>
      <span><kbd>S</kbd> Skip</span>
    </div>
  );
}

function QualityCard({
  summary,
  qcIssues,
  warning,
  failed,
}: {
  summary: ReturnType<typeof summarizeQuality>;
  qcIssues: QcIssue[];
  warning: boolean;
  failed: boolean;
}) {
  const overall = failed ? "Needs re-record" : warning ? "Acceptable" : "Good";
  return (
    <section className="quality-card">
      <div className="row spread quality-card-head">
        <div>
          <div className="quality-title">Recording Quality</div>
          <div className="muted small">A quick check of the current take</div>
        </div>
        <span className={`chip ${failed ? "bad" : warning ? "warn" : "ok"}`}>{overall}</span>
      </div>
      <div className="quality-grid">
        {summary.map((item) => (
          <div key={item.label} className="quality-item">
            <span className={`quality-dot ${item.tone}`}>{qualityIcon(item.tone)}</span>
            <div>
              <div className="quality-item-label">{item.label}</div>
              <div className="muted small">{item.value}</div>
            </div>
          </div>
        ))}
      </div>
      {!!qcIssues.length && (
        <div className="quality-notes muted small">
          {qcIssues.slice(0, 2).map((issue) => issue.message).join(" • ")}
        </div>
      )}
    </section>
  );
}

function summarizeQuality(rec: Recording) {
  const metrics = rec.qc_metrics ?? {};
  const issues = rec.qc_issues ?? [];
  const hasIssue = (codes: string[]) => issues.some((issue) => codes.includes(issue.code));
  const snr = readMetric(metrics.snr_db);
  const noiseFloor = readMetric(metrics.noise_floor_dbfs);
  const speechLevel = readMetric(metrics.speech_rms_dbfs);
  const clipRatio = readMetric(metrics.clip_ratio);

  return [
    {
      label: "Microphone level",
      tone: hasIssue(["quiet", "hot", "dc_offset"]) ? "warn" : "ok",
      value:
        speechLevel === null
          ? "Looks stable"
          : `${speechLevel.toFixed(0)} dBFS speech level`,
    },
    {
      label: "Background noise",
      tone: hasIssue(["low_snr", "snr", "noise_floor"]) ? (rec.qc_status === "failed" ? "bad" : "warn") : "ok",
      value:
        snr !== null && noiseFloor !== null
          ? `SNR ${snr.toFixed(0)} dB, noise floor ${noiseFloor.toFixed(0)} dBFS`
          : "Room noise is under control",
    },
    {
      label: "Pronunciation",
      tone:
        rec.asr_status === "major_mismatch" || rec.asr_status === "error"
          ? "bad"
          : rec.asr_status === "minor_mismatch" || rec.asr_status === "not_run"
            ? "warn"
            : "ok",
      value:
        rec.asr_status === "match"
          ? "Matches expected text"
          : rec.asr_status === "minor_mismatch"
            ? "Minor mismatch detected"
            : rec.asr_status === "major_mismatch"
              ? "Please listen carefully before saving"
              : rec.asr_status === "error"
                ? "Could not verify automatically"
                : "Not checked automatically yet",
    },
    {
      label: "Clipping",
      tone: hasIssue(["clipping"]) ? "bad" : hasIssue(["clipping_minor"]) ? "warn" : "ok",
      value:
        clipRatio !== null && clipRatio > 0
          ? `${(clipRatio * 100).toFixed(2)}% clipped samples`
          : "No clipping detected",
    },
  ] as const;
}

function readMetric(value: number | string | undefined): number | null {
  return typeof value === "number" ? value : null;
}

function workflowIcon(state: WorkflowStepState): string {
  if (state === "success") return "✓";
  if (state === "error") return "✕";
  if (state === "active") return "⋯";
  return "○";
}

function qualityIcon(tone: "ok" | "warn" | "bad"): string {
  if (tone === "ok") return "●";
  if (tone === "warn") return "▲";
  return "■";
}

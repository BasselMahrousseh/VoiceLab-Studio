import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, upload } from "../api";
import { useAuth } from "../auth";
import { listInputDevices, StudioRecorder, TakeResult } from "../audio/recorder";
import Logo from "../components/Logo";
import LevelMeter from "../components/LevelMeter";
import Waveform from "../components/Waveform";
import { Spinner } from "../components/widgets";
import { Recording, RecorderContext, Script } from "../types";

type Phase = "ready" | "recording" | "processing" | "review";

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
  const [showGuide, setShowGuide] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState(localStorage.getItem("lahja_device") || "");

  const recorder = useRef<StudioRecorder | null>(null);
  const timerRef = useRef<number>(0);
  const phaseRef = useRef<Phase>("ready");
  phaseRef.current = phase;

  const loadContext = useCallback(() => {
    get<RecorderContext>("/api/recorder/context")
      .then((c) => {
        setCtx(c);
        setScript(c.next_script);
      })
      .catch((e) => {
        setError(e.message);
        setCtx(null);
      });
  }, []);
  useEffect(loadContext, [loadContext]);

  useEffect(() => () => recorder.current?.close(), []);

  const ensureRecorder = useCallback(async (): Promise<StudioRecorder> => {
    if (!recorder.current || !recorder.current.ready) {
      const r = new StudioRecorder();
      await r.init(deviceId || undefined);
      recorder.current = r;
      setDevices(await listInputDevices());
    }
    return recorder.current;
  }, [deviceId]);

  const resetTake = useCallback(() => {
    setTake(null);
    setRec(null);
    if (takeUrl) URL.revokeObjectURL(takeUrl);
    setTakeUrl("");
  }, [takeUrl]);

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
      if (!script || !ctx?.session_id) return;
      const uploaded = await upload<Recording>("/api/recordings", result.blob, `${script.script_id}.wav`, {
        script_pk: script.id,
        session_id: ctx.session_id,
      });
      setRec(uploaded);
      setPhase("review");
    } catch (e) {
      setError((e as Error).message);
      setPhase("ready");
    }
  }, [script, ctx]);

  const save = useCallback(async () => {
    if (!rec) return;
    try {
      await post(`/api/recordings/${rec.id}/accept`, {});
      resetTake();
      setPhase("ready");
      setElapsed(0);
      loadContext();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [rec, resetTake, loadContext]);

  const restart = useCallback(async () => {
    if (rec) {
      await post(`/api/recordings/${rec.id}/reject`, { note: "re-recorded" }).catch(() => undefined);
    }
    resetTake();
    setPhase("ready");
    setElapsed(0);
  }, [rec, resetTake]);

  // keyboard: Space = record/stop, Enter = save, R = restart
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
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [startRecording, stopRecording, save, restart, rec]);

  if (ctx === undefined) return <div className="app-loading"><Spinner label="Loading your session…" /></div>;

  const progress = ctx?.progress;
  const pct = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const qcFailed = rec?.qc_status === "failed";
  const qcWarn = rec?.qc_status === "warning";

  return (
    <div className="recorder-shell">
      <header className="recorder-top">
        <div className="row gap">
          <Logo height={40} />
        </div>
        <div className="row gap">
          {ctx?.dataset && <span className="chip accent">{ctx.dataset.name}</span>}
          <span className="muted small">{user?.display_name || user?.username}</span>
          <button className="btn ghost small" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {progress && (
        <div className="recorder-progress">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="muted small">
            {progress.done} of {progress.total} recorded · {progress.remaining} to go
          </span>
        </div>
      )}

      <main className="recorder-main">
        {error && <div className="banner error">{error}</div>}

        {ctx?.dataset?.instructions && (
          <div className="guide-box">
            <button className="link-btn" onClick={() => setShowGuide(!showGuide)}>
              {showGuide ? "▾" : "▸"} Recording instructions
            </button>
            {showGuide && <pre className="guide-text">{ctx.dataset.instructions}</pre>}
          </div>
        )}

        {!script ? (
          <div className="panel done-panel fade-in">
            <div className="done-emoji">🎉</div>
            <h2>All done — thank you!</h2>
            <p className="muted">
              You've recorded every sentence in this set. You can sign out, or check back later if
              more are added.
            </p>
          </div>
        ) : (
          <>
            <div className="panel prompt-panel fade-in" key={script.id}>
              <div className="prompt-label muted small">Please read aloud</div>
              <div className="arabic prompt-text" dir="rtl">
                {script.display_text}
              </div>
              {script.notes && <div className="muted small note-line">📝 {script.notes}</div>}
            </div>

            <div className="panel record-panel">
              {phase !== "review" && (
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
                    <div className="record-meta">
                      <span className={`timer big ${phase === "recording" ? "live" : ""}`}>
                        {formatTimer(elapsed)}
                      </span>
                      <span className="muted small">
                        Press <kbd>Space</kbd> to {phase === "recording" ? "stop" : "start"}
                      </span>
                    </div>
                  </div>
                  <LevelMeter recorder={recorder.current} active={phase === "recording"} />
                  {phase === "processing" && <Spinner label="Processing…" />}
                </>
              )}

              {phase === "review" && take && rec && (
                <div className="review-block fade-in">
                  <Waveform samples={take.samples} />
                  <audio controls src={takeUrl} className="player" />
                  {qcFailed && (
                    <div className="banner error">
                      This take looks too short or too quiet. Please press <b>Restart</b> and read it
                      again.
                    </div>
                  )}
                  {qcWarn && !qcFailed && (
                    <div className="banner warn small">
                      Audio saved — quality looks a little off, but it's usable. Restart if you'd
                      like a cleaner take.
                    </div>
                  )}
                  <div className="row gap action-row">
                    <button className="btn accept big" onClick={save} disabled={qcFailed}>
                      ✓ Save &amp; next <kbd>Enter</kbd>
                    </button>
                    <button className="btn big" onClick={restart}>
                      ↺ Restart <kbd>R</kbd>
                    </button>
                  </div>
                </div>
              )}
            </div>

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

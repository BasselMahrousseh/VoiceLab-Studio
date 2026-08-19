/** Raw-PCM studio recorder.
 *
 * Deliberately avoids MediaRecorder: browsers encode it to lossy Opus/WebM,
 * which is unacceptable for TTS training masters. Instead an AudioWorklet
 * captures Float32 PCM which is encoded as WAV client-side.
 *
 * Browser DSP (echo cancellation, noise suppression, auto gain) is disabled:
 * those processors mangle voice timbre and dynamics; a controlled booth plus
 * QC checks replace them.
 */
import { encodeWavFloat32 } from "./wav";

export interface TakeResult {
  blob: Blob;
  samples: Float32Array;
  sampleRate: number;
  durationSec: number;
}

const WORKLET_CODE = `
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = [];
    this.len = 0;
    this.port.onmessage = () => {   // flush request
      this.flush();
      this.port.postMessage("flushed");
    };
  }
  flush() {
    if (!this.len) return;
    const out = new Float32Array(this.len);
    let o = 0;
    for (const b of this.buf) { out.set(b, o); o += b.length; }
    this.port.postMessage(out, [out.buffer]);
    this.buf = [];
    this.len = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      this.buf.push(new Float32Array(ch));
      this.len += ch.length;
      if (this.len >= 4096) this.flush();
    }
    return true;
  }
}
registerProcessor("pcm-capture", PCMCapture);
`;

export class StudioRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private analyser: AnalyserNode | null = null;
  private chunks: Float32Array[] = [];
  private flushResolve: (() => void) | null = null;
  private levelBuf: Float32Array<ArrayBuffer> | null = null;
  recording = false;
  sampleRate = 0;
  deviceLabel = "";

  get ready(): boolean {
    return !!this.ctx && !!this.stream && this.stream.getAudioTracks()[0]?.readyState === "live";
  }

  async init(deviceId?: string): Promise<void> {
    this.close();
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        channelCount: 1,
        sampleRate: 48000,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    const track = this.stream.getAudioTracks()[0];
    this.deviceLabel = track?.label ?? "";

    this.ctx = new AudioContext({ sampleRate: 48000 });
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.sampleRate = this.ctx.sampleRate;

    const url = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "application/javascript" }));
    try {
      await this.ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }

    const source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
    });
    this.node.port.onmessage = (e: MessageEvent) => {
      if (e.data === "flushed") {
        this.flushResolve?.();
        this.flushResolve = null;
      } else if (this.recording && e.data instanceof Float32Array) {
        this.chunks.push(e.data);
      }
    };
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    source.connect(this.node);
    source.connect(this.analyser);
    // NOT connected to ctx.destination: no monitoring loop / feedback risk.
  }

  start(): void {
    if (!this.ready) throw new Error("Recorder not initialized");
    this.chunks = [];
    this.recording = true;
  }

  async stop(): Promise<TakeResult> {
    if (!this.node) throw new Error("Recorder not initialized");
    // Ask the worklet to flush its partial buffer, then wait for it so the
    // tail of the last word is never lost.
    await new Promise<void>((resolve) => {
      this.flushResolve = resolve;
      this.node!.port.postMessage("flush");
      setTimeout(resolve, 500); // safety net
    });
    this.recording = false;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const samples = new Float32Array(total);
    let o = 0;
    for (const c of this.chunks) {
      samples.set(c, o);
      o += c.length;
    }
    this.chunks = [];
    return {
      blob: encodeWavFloat32(samples, this.sampleRate),
      samples,
      sampleRate: this.sampleRate,
      durationSec: total / this.sampleRate,
    };
  }

  /** Instantaneous level for the meter: {rms, peak} in linear 0..1. */
  level(): { rms: number; peak: number } {
    if (!this.analyser) return { rms: 0, peak: 0 };
    if (!this.levelBuf || this.levelBuf.length !== this.analyser.fftSize) {
      this.levelBuf = new Float32Array(this.analyser.fftSize);
    }
    this.analyser.getFloatTimeDomainData(this.levelBuf);
    let sum = 0;
    let peak = 0;
    for (let i = 0; i < this.levelBuf.length; i++) {
      const v = Math.abs(this.levelBuf[i]);
      sum += v * v;
      if (v > peak) peak = v;
    }
    return { rms: Math.sqrt(sum / this.levelBuf.length), peak };
  }

  close(): void {
    this.recording = false;
    this.node?.port.close();
    this.node = null;
    this.analyser = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}

export async function listInputDevices(): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "audioinput" && d.deviceId);
}

/** Request mic permission, then enumerate inputs (labels appear after permission). */
export async function requestInputDevices(deviceId?: string): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices?.getUserMedia) {
    return listInputDevices();
  }
  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
  } catch {
    // Permission denied or device unavailable — still try best-effort enumeration.
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
  return listInputDevices();
}

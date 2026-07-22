"""Automatic audio quality checks for every recorded take.

Design notes:
- Severities: "fail" (blocks acceptance by default), "warn" (reviewer decides),
  "info" (context only). Overall qc_status = failed / warning / passed.
- The speech/silence segmentation uses an adaptive frame-RMS threshold anchored
  to the measured noise floor, so it works across mic gains.
- Echo/reverb is NOT estimated automatically (unreliable without a reference);
  room quality is covered by the noise-floor/SNR checks, the session room-tone
  check, and human listening.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

from ..config import Settings
from .audio_io import LoadedAudio

FRAME_SEC = 0.05
HOP_SEC = 0.02
EPS = 1e-12


@dataclass
class QcResult:
    status: str = "passed"  # passed | warning | failed
    issues: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    audio_sha256: str = ""

    def add(self, severity: str, code: str, message: str, value: float | None = None):
        item: dict = {"severity": severity, "code": code, "message": message}
        if value is not None:
            item["value"] = round(float(value), 4)
        self.issues.append(item)


def _dbfs(x: float) -> float:
    return 20.0 * math.log10(max(x, EPS))


def frame_rms_db(x: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    """Frame-wise RMS in dBFS. Returns (frames_db, hop_sec)."""
    frame = max(1, int(FRAME_SEC * rate))
    hop = max(1, int(HOP_SEC * rate))
    if len(x) < frame:
        rms = float(np.sqrt(np.mean(x**2))) if len(x) else 0.0
        return np.array([_dbfs(rms)]), HOP_SEC
    # vectorized frame energies via cumulative sum of squares
    csum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    starts = np.arange(0, len(x) - frame + 1, hop)
    energies = (csum[starts + frame] - csum[starts]) / frame
    rms = np.sqrt(np.maximum(energies, 0.0))
    return 20.0 * np.log10(np.maximum(rms, EPS)), hop / rate


def analyze_recording(audio: LoadedAudio, settings: Settings, raw_bytes: bytes | None = None) -> QcResult:
    r = QcResult()
    m = r.metrics

    # --- container / format checks -----------------------------------------
    m["sample_rate"] = audio.sample_rate
    m["channels"] = audio.channels
    m["subtype"] = audio.subtype
    m["duration_sec"] = round(audio.duration_sec, 3)

    if audio.channels != 1:
        r.add("fail", "not_mono", f"Expected mono audio, got {audio.channels} channels")
    if audio.sample_rate < 16000:
        r.add("fail", "low_sample_rate", f"Sample rate {audio.sample_rate} Hz is below 16 kHz")

    x = audio.mono()
    if raw_bytes is not None:
        r.audio_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    dur = audio.duration_sec
    if dur < settings.qc_hard_min_duration_sec:
        r.add("fail", "too_short", f"Duration {dur:.2f}s is below the hard minimum "
              f"{settings.qc_hard_min_duration_sec}s", dur)
    elif dur < settings.qc_warn_min_duration_sec:
        r.add("warn", "short", f"Duration {dur:.2f}s is shorter than typical", dur)
    if dur > settings.qc_hard_max_duration_sec:
        r.add("fail", "too_long", f"Duration {dur:.2f}s exceeds the hard maximum "
              f"{settings.qc_hard_max_duration_sec}s", dur)
    elif dur > settings.qc_warn_max_duration_sec:
        r.add("warn", "long", f"Duration {dur:.2f}s is longer than typical", dur)

    if not len(x):
        r.add("fail", "empty", "Audio file contains no samples")
        r.status = "failed"
        return r

    # --- level metrics ------------------------------------------------------
    peak = float(np.max(np.abs(x)))
    rms_all = float(np.sqrt(np.mean(x**2)))
    m["peak_dbfs"] = round(_dbfs(peak), 2)
    m["rms_dbfs"] = round(_dbfs(rms_all), 2)

    dc = float(np.mean(x))
    m["dc_offset"] = round(dc, 5)
    if abs(dc) > settings.qc_dc_offset_warn:
        r.add("warn", "dc_offset", f"DC offset {dc:.4f} detected (check interface/driver)", dc)

    # clipping: samples at/above full scale, and the longest consecutive run
    clipped = np.abs(x) >= settings.qc_clip_threshold
    clip_count = int(np.count_nonzero(clipped))
    m["clip_count"] = clip_count
    m["clip_ratio"] = round(clip_count / len(x), 6)
    if clip_count:
        # longest run of consecutive clipped samples
        idx = np.flatnonzero(clipped)
        runs = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
        m["clip_max_run"] = int(max(len(run) for run in runs))
    else:
        m["clip_max_run"] = 0
    if m["clip_ratio"] > settings.qc_clip_fail_ratio:
        r.add("fail", "clipping", f"{clip_count} clipped samples "
              f"({m['clip_ratio']*100:.3f}%) - reduce input gain and re-record", m["clip_ratio"])
    elif clip_count > settings.qc_clip_warn_count:
        r.add("warn", "clipping_minor", f"{clip_count} samples at full scale", clip_count)

    # --- loudness (LUFS) ----------------------------------------------------
    if dur >= 0.5:
        try:
            import pyloudnorm as pyln

            loudness = pyln.Meter(audio.sample_rate).integrated_loudness(x)
            if math.isfinite(loudness):
                m["lufs"] = round(float(loudness), 2)
        except Exception:
            pass

    # --- speech / silence segmentation ---------------------------------------
    frames_db, hop_sec = frame_rms_db(x, audio.sample_rate)
    noise_floor = float(np.percentile(frames_db, 10))
    m["noise_floor_dbfs"] = round(noise_floor, 2)
    speech_thresh = max(noise_floor + 12.0, -45.0)
    speech = frames_db > speech_thresh
    speech_ratio = float(np.mean(speech))
    m["speech_ratio"] = round(speech_ratio, 3)

    if speech_ratio < settings.qc_speech_ratio_fail:
        r.add("fail", "near_empty", "Recording is mostly silence "
              f"(speech ratio {speech_ratio:.0%})", speech_ratio)
    else:
        speech_idx = np.flatnonzero(speech)
        lead = speech_idx[0] * hop_sec
        trail = (len(speech) - 1 - speech_idx[-1]) * hop_sec
        m["leading_silence_sec"] = round(float(lead), 2)
        m["trailing_silence_sec"] = round(float(trail), 2)
        if lead > settings.qc_lead_trail_warn_sec:
            r.add("warn", "long_lead_silence", f"{lead:.1f}s of silence before speech", lead)
        if trail > settings.qc_lead_trail_warn_sec:
            r.add("warn", "long_trail_silence", f"{trail:.1f}s of silence after speech", trail)
        if lead < settings.qc_abrupt_start_sec:
            r.add("warn", "abrupt_start", "Speech starts immediately - first word may be cut off")

        # longest internal pause between speech frames
        gaps = np.diff(speech_idx)
        max_gap_sec = float((gaps.max() - 1) * hop_sec) if len(gaps) and gaps.max() > 1 else 0.0
        m["max_internal_silence_sec"] = round(max_gap_sec, 2)
        if max_gap_sec > settings.qc_internal_silence_warn_sec:
            r.add("warn", "internal_silence", f"{max_gap_sec:.1f}s pause inside the utterance",
                  max_gap_sec)

        # speech level and SNR
        speech_rms_db = float(np.percentile(frames_db[speech], 60))
        m["speech_rms_dbfs"] = round(speech_rms_db, 2)
        snr = speech_rms_db - noise_floor
        m["snr_db"] = round(snr, 2)
        if snr < settings.qc_snr_fail_db:
            r.add("fail", "low_snr", f"SNR {snr:.0f} dB is too low (noisy or too quiet)", snr)
        elif snr < settings.qc_snr_warn_db:
            r.add("warn", "snr", f"SNR {snr:.0f} dB is below target", snr)

        if speech_rms_db < settings.qc_rms_warn_low_dbfs:
            r.add("warn", "quiet", f"Speech level {speech_rms_db:.0f} dBFS is low - "
                  "raise input gain", speech_rms_db)
        elif speech_rms_db > settings.qc_rms_warn_high_dbfs:
            r.add("warn", "hot", f"Speech level {speech_rms_db:.0f} dBFS is hot - "
                  "lower input gain", speech_rms_db)

    if noise_floor > settings.qc_noise_floor_warn_dbfs:
        r.add("warn", "noise_floor", f"Noise floor {noise_floor:.0f} dBFS is high "
              "(check room/mic)", noise_floor)

    # --- overall status -------------------------------------------------------
    severities = {i["severity"] for i in r.issues}
    if "fail" in severities:
        r.status = "failed"
    elif "warn" in severities:
        r.status = "warning"
    else:
        r.status = "passed"
    return r


def analyze_room_tone(audio: LoadedAudio, settings: Settings) -> dict:
    """Noise-floor measurement for a short 'silence' capture at session start."""
    x = audio.mono()
    if not len(x):
        return {"room_tone_dbfs": 0.0, "status": "warn", "message": "Empty capture"}
    frames_db, _ = frame_rms_db(x, audio.sample_rate)
    floor = float(np.percentile(frames_db, 50))
    status = "ok" if floor <= settings.room_tone_warn_dbfs else "warn"
    message = (
        f"Room noise floor {floor:.0f} dBFS - good to record"
        if status == "ok"
        else f"Room noise floor {floor:.0f} dBFS is above the {settings.room_tone_warn_dbfs:.0f} dBFS target - check A/C, fans, mic gain"
    )
    return {"room_tone_dbfs": round(floor, 2), "status": status, "message": message}


def find_speech_bounds(x: np.ndarray, rate: int) -> tuple[int, int]:
    """Sample indices of speech start/end (for export-time silence trimming)."""
    frames_db, hop_sec = frame_rms_db(x, rate)
    noise_floor = float(np.percentile(frames_db, 10))
    speech = frames_db > max(noise_floor + 12.0, -45.0)
    idx = np.flatnonzero(speech)
    if not len(idx):
        return 0, len(x)
    hop = int(hop_sec * rate)
    start = int(idx[0] * hop)
    end = min(len(x), int((idx[-1] + 1) * hop + int(FRAME_SEC * rate)))
    return start, end

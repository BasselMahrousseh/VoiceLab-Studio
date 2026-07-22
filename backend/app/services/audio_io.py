"""WAV reading/writing and resampling helpers (no ffmpeg dependency)."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


@dataclass
class LoadedAudio:
    samples: np.ndarray  # float64, shape (n,) mono or (n, ch)
    sample_rate: int
    channels: int
    subtype: str  # e.g. FLOAT, PCM_16
    frames: int

    @property
    def duration_sec(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0

    def mono(self) -> np.ndarray:
        if self.samples.ndim == 1:
            return self.samples
        return self.samples.mean(axis=1)


def load_wav(source: str | Path | bytes) -> LoadedAudio:
    """Load a WAV file (path or raw bytes) as float64 in [-1, 1]."""
    if isinstance(source, bytes):
        data, rate = sf.read(io.BytesIO(source), dtype="float64", always_2d=False)
        with sf.SoundFile(io.BytesIO(source)) as f:
            subtype, channels, frames = f.subtype, f.channels, f.frames
    else:
        data, rate = sf.read(str(source), dtype="float64", always_2d=False)
        with sf.SoundFile(str(source)) as f:
            subtype, channels, frames = f.subtype, f.channels, f.frames
    return LoadedAudio(
        samples=data, sample_rate=int(rate), channels=channels, subtype=subtype, frames=frames
    )


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """High-quality polyphase resampling."""
    if src_rate == dst_rate:
        return samples
    g = math.gcd(src_rate, dst_rate)
    return resample_poly(samples, dst_rate // g, src_rate // g)


def write_wav_pcm16(path: str | Path, samples: np.ndarray, rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), clipped, rate, subtype="PCM_16")


def wav_bytes_pcm16(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(samples, -1.0, 1.0), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def peak_normalize(samples: np.ndarray, target_dbfs: float = -3.0) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0:
        return samples
    target = 10 ** (target_dbfs / 20.0)
    return samples * (target / peak)


def loudness_normalize(samples: np.ndarray, rate: int, target_lufs: float = -20.0) -> np.ndarray:
    """Integrated-loudness normalization via pyloudnorm; safe fallback to peak."""
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(rate)
        loudness = meter.integrated_loudness(samples)
        if not math.isfinite(loudness):
            return peak_normalize(samples)
        gain_db = target_lufs - loudness
        out = samples * (10 ** (gain_db / 20.0))
        peak = float(np.max(np.abs(out))) if out.size else 0.0
        if peak > 0.985:  # keep ~0.13 dB headroom; avoid clipping from the gain
            out = out * (0.985 / peak)
        return out
    except Exception:
        return peak_normalize(samples)

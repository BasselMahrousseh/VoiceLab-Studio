import io
import json

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import text_normalize as tn
from app.services.audio_io import load_wav
from app.services.audio_qc import analyze_recording


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def synth_speech(duration=5.0, rate=48000, amp=0.3, noise=1e-4, lead=0.4, trail=0.4):
    """Speech-like signal: modulated tone bursts with pauses + tiny noise floor."""
    n = int(duration * rate)
    t = np.arange(n) / rate
    x = np.random.default_rng(42).normal(0, noise, n)
    burst = np.zeros(n)
    pos = lead
    while pos < duration - trail - 0.6:
        seg = slice(int(pos * rate), int((pos + 0.5) * rate))
        tt = t[seg]
        burst[seg] = np.sin(2 * np.pi * 180 * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * tt))
        pos += 0.75
    return (x + amp * burst).astype(np.float32)


def wav_bytes(x, rate=48000, subtype="FLOAT"):
    buf = io.BytesIO()
    sf.write(buf, x, rate, format="WAV", subtype=subtype)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# text normalization
# ---------------------------------------------------------------------------
def test_normalize_diacritics_and_folding():
    assert tn.normalize_arabic("شُو تَبْغِي؟") == tn.normalize_arabic("شو تبغي")
    assert tn.normalize_arabic("أحمد إلى ىة") == tn.normalize_arabic("احمد الي يه")
    assert tn.normalize_arabic("٢٤") == "24"


def test_digit_verbalization_comparison():
    r = tn.compare_for_asr("عندك 24 ساعة", "عندك أربعة وعشرون ساعة")
    assert r["cer"] < 0.05  # digits verbalized on both sides -> near match


def test_cer_detects_real_mismatch():
    r = tn.compare_for_asr("شو تبغي أسويلك اليوم", "وين تبغي تروح باجر")
    assert r["cer"] > 0.3


def test_helpers():
    assert tn.has_latin("باقة du") and not tn.has_latin("مرحبا")
    assert tn.has_digits("24") and tn.has_digits("٢٤")
    assert tn.length_bucket("شو تبغي") == "short"


# ---------------------------------------------------------------------------
# audio QC
# ---------------------------------------------------------------------------
def _qc(x, rate=48000):
    raw = wav_bytes(x, rate)
    return analyze_recording(load_wav(raw), get_settings(), raw_bytes=raw)


def test_qc_clean_recording_passes():
    r = _qc(synth_speech())
    assert r.status in ("passed", "warning")
    assert not any(i["severity"] == "fail" for i in r.issues)
    m = r.metrics
    assert 4.9 < m["duration_sec"] < 5.1
    assert m["snr_db"] > 30
    assert m["clip_count"] == 0
    assert 0.3 < m["leading_silence_sec"] < 0.6
    assert r.audio_sha256


def test_qc_clipping_fails():
    x = synth_speech(amp=1.4)
    r = _qc(np.clip(x, -1.0, 1.0))
    assert r.status == "failed"
    assert any(i["code"] == "clipping" for i in r.issues)


def test_qc_silence_fails():
    x = np.random.default_rng(1).normal(0, 1e-4, 48000 * 3).astype(np.float32)
    r = _qc(x)
    assert r.status == "failed"
    assert any(i["code"] == "near_empty" for i in r.issues)


def test_qc_too_short_fails():
    r = _qc(synth_speech(duration=0.5, lead=0.05, trail=0.05))
    assert any(i["code"] == "too_short" for i in r.issues)


# ---------------------------------------------------------------------------
# full API flow: import -> session -> record -> accept -> export
# ---------------------------------------------------------------------------
def _login(client, username="admin", password="changeme"):
    tok = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {tok}"
    return tok


def test_full_api_flow(tmp_path):
    with TestClient(app) as client:
        # unauthenticated calls are rejected
        assert client.get("/api/status").status_code == 401
        _login(client)

        # status
        st = client.get("/api/status").json()
        assert st["llm_configured"] is False and st["asr_configured"] is False

        # default speaker seeded
        speakers = client.get("/api/speakers").json()
        assert speakers and speakers[0]["speaker_key"] == "speaker_001"

        # import: one valid, one violating the numbers policy
        resp = client.post(
            "/api/scripts/import",
            json={
                "items": [
                    {
                        "display_text": "هلا، كيف أقدر أساعدك اليوم؟",
                        "style": "friendly",
                        "domain": "customer_support",
                    },
                    {
                        "display_text": "عندك 24 ساعة",
                        "training_text": "عندك 24 ساعة",
                        "style": "neutral",
                    },
                ]
            },
        ).json()
        assert resp["imported"] == 1
        assert len(resp["skipped"]) == 1
        assert "digits" in resp["skipped"][0]["errors"][0]
        script = resp["items"][0]
        assert script["script_id"].startswith("AE_FRIENDLY_")
        assert script["training_text"] == script["display_text"]

        # duplicate import is rejected
        dup = client.post(
            "/api/scripts/import",
            json={"items": [{"display_text": "هلا، كيف أقدر أساعدك اليوم؟"}]},
        ).json()
        assert dup["imported"] == 0

        # session
        session = client.post(
            "/api/sessions/start",
            json={"speaker_id": speakers[0]["id"], "device_info": {"ua": "pytest"}},
        ).json()

        # next script
        nxt = client.get("/api/scripts/next").json()
        assert nxt["id"] == script["id"]

        # upload a take
        raw = wav_bytes(synth_speech())
        rec = client.post(
            "/api/recordings",
            data={"script_pk": script["id"], "session_id": session["id"]},
            files={"file": ("take.wav", raw, "audio/wav")},
        ).json()
        assert rec["qc_status"] in ("passed", "warning")
        assert rec["take_number"] == 1
        assert rec["qc_metrics"]["snr_db"] > 30

        # identical re-upload is flagged as duplicate audio
        rec2 = client.post(
            "/api/recordings",
            data={"script_pk": script["id"], "session_id": session["id"]},
            files={"file": ("take2.wav", raw, "audio/wav")},
        ).json()
        assert any(i["code"] == "duplicate_audio" for i in rec2["qc_issues"])

        # audio can be streamed back
        audio_resp = client.get(f"/api/recordings/{rec['id']}/audio")
        assert audio_resp.status_code == 200
        assert audio_resp.headers["content-type"].startswith("audio/wav")

        # reject the duplicate, accept the first with an edited transcript
        client.post(f"/api/recordings/{rec2['id']}/reject", json={"note": "dup"})
        accepted = client.post(
            f"/api/recordings/{rec['id']}/accept",
            json={"final_text": "هلا والله، كيف أقدر أساعدك اليوم؟"},
        ).json()
        assert accepted["human_status"] == "accepted"
        assert accepted["text_edited"] is True

        # script is now done and leaves the queue
        assert client.get("/api/scripts/next").json() is None
        stats = client.get("/api/scripts/stats").json()
        assert stats["by_status"]["done"] == 1

        # ASR verify without config -> 503
        assert client.post(f"/api/recordings/{rec['id']}/verify").status_code == 503

        # export
        batch = client.post(
            "/api/exports", json={"name": "smoke", "sample_rate": 24000}
        ).json()
        assert batch["status"] == "done"
        assert batch["file_count"] == 1

        settings = get_settings()
        root = settings.export_dir / batch["rel_path"]
        wavs = list(root.glob("speaker_001/wavs/*.wav"))
        assert len(wavs) == 1
        info = sf.info(str(wavs[0]))
        assert info.samplerate == 24000
        assert info.channels == 1
        assert info.subtype == "PCM_16"

        meta = [
            json.loads(line)
            for line in (root / "metadata.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert meta[0]["text"] == "هلا والله، كيف أقدر أساعدك اليوم؟"
        assert meta[0]["audio_path"].startswith("speaker_001/wavs/")
        assert (root / "metadata.csv").exists()
        assert (root / "qc_report.json").exists()
        assert (root / "dataset_card.md").exists()

        # zip download
        dl = client.get(f"/api/exports/{batch['id']}/download")
        assert dl.status_code == 200

        # end session
        ended = client.post(f"/api/sessions/{session['id']}/end").json()
        assert ended["ended_at"] is not None
        assert ended["recording_count"] == 2
        assert ended["accepted_count"] == 1


def test_auth_and_recorder_flow():
    with TestClient(app) as client:
        _login(client)  # admin

        # admin creates a dataset with recording instructions
        ds = client.post(
            "/api/datasets",
            json={
                "name": "Emirati Support Pilot",
                "instructions": "Speak naturally in Emirati dialect.",
            },
        ).json()
        assert ds["slug"] == "emirati-support-pilot"

        # add two scripts to the dataset
        added = client.post(
            f"/api/datasets/{ds['id']}/scripts",
            json={"text": "هلا شحالك اليوم؟\nشو تبغي أسويلك؟", "style": "friendly"},
        ).json()
        assert added["imported"] == 2

        # admin creates a recorder assigned to the dataset
        rec_user = client.post(
            f"/api/datasets/{ds['id']}/recorders",
            json={"username": "reader1", "password": "pass123", "display_name": "Reader One"},
        ).json()
        assert rec_user["role"] == "recorder"
        assert rec_user["dataset_id"] == ds["id"]
        assert rec_user["speaker_id"] is not None

        # recorders cannot reach admin surfaces
        rec_client = TestClient(app)
        _login(rec_client, "reader1", "pass123")
        assert rec_client.get("/api/datasets").status_code == 403

        # recorder context: dataset, session and first script to read
        ctx = rec_client.get("/api/recorder/context").json()
        assert ctx["dataset"]["id"] == ds["id"]
        assert ctx["session_id"] is not None
        assert ctx["progress"] == {"total": 2, "done": 0, "remaining": 2}
        first = ctx["next_script"]
        assert first is not None

        # recorder records and saves the first script
        raw = wav_bytes(synth_speech())
        rec = rec_client.post(
            "/api/recordings",
            data={"script_pk": first["id"], "session_id": ctx["session_id"]},
            files={"file": ("take.wav", raw, "audio/wav")},
        ).json()
        rec_client.post(f"/api/recordings/{rec['id']}/accept", json={})

        # progress advances and the next script differs
        ctx2 = rec_client.get("/api/recorder/context").json()
        assert ctx2["progress"] == {"total": 2, "done": 1, "remaining": 1}
        assert ctx2["next_script"]["id"] != first["id"]

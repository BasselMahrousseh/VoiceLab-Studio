"""Optional ASR verification layer.

ASR is advisory only: it flags takes where the speaker likely skipped, added
or substituted words. It never overwrites the transcript — reviewers decide.

Note: the script text is deliberately NOT passed as a Whisper prompt. Priming
the model with the expected sentence would bias it toward "hearing" the
script, defeating the purpose of verification.
"""
from __future__ import annotations

import io
from pathlib import Path

from ..config import Settings
from . import text_normalize as tn


def _client(settings: Settings):
    if settings.asr_provider == "azure":
        from openai import AzureOpenAI
        kwargs = {
            "azure_endpoint": (
                settings.asr_azure_endpoint or settings.azure_openai_endpoint
            ),
            "api_version": (
                settings.asr_azure_api_version
                or settings.azure_openai_api_version
            ),
        }
        key = settings.asr_azure_api_key or settings.azure_openai_api_key
        if key:
            kwargs["api_key"] = key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = DefaultAzureCredential(
                managed_identity_client_id=settings.azure_client_id or None,
                exclude_interactive_browser_credential=True,
            )
            kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
        return AzureOpenAI(**kwargs)
    from openai import OpenAI

    return OpenAI(
        base_url=settings.asr_openai_base_url or settings.openai_base_url or None,
        api_key=settings.asr_openai_api_key or settings.openai_api_key or "not-needed",
    )


def transcribe(
    wav_source: Path | bytes, settings: Settings, language: str | None = None
) -> str:
    client = _client(settings)
    if isinstance(wav_source, bytes):
        f = io.BytesIO(wav_source)
        f.name = "take.wav"
        close = f.close
    else:
        f = open(wav_source, "rb")
        close = f.close
    try:
        kwargs = {
            "model": settings.asr_deployment,
            "file": f,
            "response_format": "json",
            "temperature": 0.0,
        }
        detected_language = settings.asr_language if language is None else language
        if detected_language:
            kwargs["language"] = detected_language
        result = client.audio.transcriptions.create(
            **kwargs
        )
    finally:
        close()
    return (result.text or "").strip()


def verify_against_script(
    wav_source: Path | bytes,
    script_text: str,
    settings: Settings,
    language: str | None = None,
) -> dict:
    """Transcribe and score against the intended transcript.

    Returns {status, asr_text, cer, wer, detail}. Status is one of
    match / minor_mismatch / major_mismatch / error.
    """
    try:
        asr_text = transcribe(wav_source, settings, language)
    except Exception as exc:  # endpoint/config errors surface to the reviewer
        return {
            "status": "error",
            "asr_text": None,
            "cer": None,
            "wer": None,
            "detail": {"error": f"{type(exc).__name__}: {exc}"},
        }

    cmp = tn.compare_for_asr(
        script_text, asr_text, digits_to_words=settings.asr_verbalize_digits
    )
    if cmp["has_latin"]:
        match_t, minor_t = settings.asr_cer_match_latin, settings.asr_cer_minor_latin
    else:
        match_t, minor_t = settings.asr_cer_match, settings.asr_cer_minor

    cer = cmp["cer"]
    if cer <= match_t:
        status = "match"
    elif cer <= minor_t:
        status = "minor_mismatch"
    else:
        status = "major_mismatch"

    return {
        "status": status,
        "asr_text": asr_text,
        "cer": cer,
        "wer": cmp["wer"],
        "detail": {
            "normalized_ref": cmp["normalized_ref"],
            "normalized_hyp": cmp["normalized_hyp"],
            "has_latin": cmp["has_latin"],
            "thresholds": {"match": match_t, "minor": minor_t},
        },
    }

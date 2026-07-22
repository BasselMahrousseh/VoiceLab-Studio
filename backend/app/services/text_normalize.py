"""Arabic text normalization and comparison utilities.

IMPORTANT DESIGN RULE: normalization here is used ONLY for
  * duplicate detection in the script bank, and
  * ASR-vs-script comparison scoring.
Stored transcripts (display_text / training_text / final_text) are NEVER
normalized or rewritten -- Emirati wording is preserved exactly as authored.

Unicode ranges are written as explicit escapes to avoid any editor/encoding
ambiguity. Key codepoints:
  0621-064A Arabic letters      064B-065F harakat/tanween    0640 tatweel
  0660-0669 Arabic-Indic digits 06F0-06F9 extended digits    0670 dagger alef
"""
from __future__ import annotations

import hashlib
import re

from rapidfuzz.distance import Levenshtein

# Arabic combining marks: harakat, tanween, shadda, sukun, dagger alef, Quranic marks
_DIACRITICS_RE = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭ]"
)
_TATWEEL = "ـ"

# Arabic-Indic (0660-0669) and Extended/Persian (06F0-06F9) digits -> ASCII
_DIGIT_TRANS = str.maketrans(
    "".join(chr(c) for c in range(0x0660, 0x066A))
    + "".join(chr(c) for c in range(0x06F0, 0x06FA)),
    "0123456789" * 2,
)

# Keep Arabic letters, ASCII letters/digits, Persian letter variants and
# whitespace; everything else (punctuation, symbols) becomes a space.
_NON_TEXT_RE = re.compile(
    "[^0-9A-Za-zء-ي٠-٩۰-۹"
    "پچڤگکی\\s]"
)
_WS_RE = re.compile(r"\s+")

_LATIN_RE = re.compile(r"[A-Za-z]")
_ARABIC_LETTER_RE = re.compile("[ء-ي]")
_DIGIT_RE = re.compile("[0-9٠-٩۰-۹]")

# Character folding for comparison (alef/hamza variants, taa marbuta, etc.)
_ALEF_RE = re.compile("[أإآٱ]")  # أ إ آ ٱ -> ا
_FOLD_MAP = str.maketrans(
    {
        "ؤ": "و",  # ؤ -> و
        "ئ": "ي",  # ئ -> ي
        "ى": "ي",  # ى -> ي
        "ة": "ه",  # ة -> ه
        # Persian/Urdu variants occasionally produced by LLMs or keyboards
        "گ": "ك",  # گ -> ك
        "پ": "ب",  # پ -> ب
        "چ": "ج",  # چ -> ج
        "ڤ": "ف",  # ڤ -> ف
        "ک": "ك",  # ک -> ك
        "ی": "ي",  # ی -> ي
    }
)


def strip_diacritics(text: str) -> str:
    return _DIACRITICS_RE.sub("", text).replace(_TATWEEL, "")


def normalize_arabic(
    text: str, *, fold_hamza: bool = True, digits_to_words: bool = False
) -> str:
    """Normalize for comparison/dedup (NOT for storage)."""
    t = strip_diacritics(text)
    t = t.translate(_DIGIT_TRANS)
    if digits_to_words:
        # before folding: num2words output contains unfolded alef/taa marbuta
        t = strip_diacritics(verbalize_digits(t))
    if fold_hamza:
        t = _ALEF_RE.sub("ا", t)
        t = t.replace("ء", "")  # bare hamza
    t = t.translate(_FOLD_MAP)
    t = _NON_TEXT_RE.sub(" ", t)
    t = t.lower()
    return _WS_RE.sub(" ", t).strip()


def verbalize_digits(text: str) -> str:
    """Best-effort conversion of integer digit groups to Arabic words.

    Used only to make ASR comparison fair when scripts contain digits the
    speaker verbalizes. Falls back to the original token on any failure.
    """
    try:
        from num2words import num2words
    except Exception:  # pragma: no cover - dependency missing
        return text

    def _repl(m: re.Match) -> str:
        s = m.group(0)
        try:
            n = int(s)
            if n > 10**12:
                return s
            return " " + num2words(n, lang="ar") + " "
        except Exception:
            return s

    return re.sub(r"\d+", _repl, text)


def normalized_hash(text: str) -> str:
    return hashlib.sha256(normalize_arabic(text).encode("utf-8")).hexdigest()


def has_latin(text: str) -> bool:
    return bool(_LATIN_RE.search(text))


def has_digits(text: str) -> bool:
    return bool(_DIGIT_RE.search(text))


def arabic_ratio(text: str) -> float:
    letters = _ARABIC_LETTER_RE.findall(text)
    visible = re.findall(r"\S", text)
    return len(letters) / max(1, len(visible))


def word_count(text: str) -> int:
    return len([w for w in _WS_RE.split(text.strip()) if w])


def length_bucket(text: str) -> str:
    n = word_count(text)
    if n <= 5:
        return "short"
    if n <= 14:
        return "medium"
    return "long"


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate on already-normalized strings."""
    ref = reference.replace(" ", "")
    hyp = hypothesis.replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate on already-normalized strings."""
    ref = reference.split()
    hyp = hypothesis.split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def compare_for_asr(
    script_text: str, asr_text: str, *, digits_to_words: bool = True
) -> dict:
    """Compare the intended transcript with ASR output.

    Returns normalized forms and CER/WER so thresholds can be applied by the
    caller. Digit verbalization is applied to BOTH sides so "24" vs the spoken
    Arabic words for twenty-four does not count as an error.
    """
    ref = normalize_arabic(script_text, digits_to_words=digits_to_words)
    hyp = normalize_arabic(asr_text, digits_to_words=digits_to_words)
    return {
        "normalized_ref": ref,
        "normalized_hyp": hyp,
        "cer": round(cer(ref, hyp), 4),
        "wer": round(wer(ref, hyp), 4),
        "has_latin": has_latin(script_text),
    }

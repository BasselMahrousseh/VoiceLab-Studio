"""Emirati dialect lexical governance for voice-script generation.

EMIRATI LEXICAL CONSISTENCY is mandatory for dialect=emirati Arabic items.

Hard constraints live here (validation). Safe, meaning-preserving rewrites are
applied only when the replacement cannot flip meaning or grammar. When
uncertain, prefer rejection over an unsafe rewrite so the item can be
regenerated.

ONLY apply lexical rules when dialect == "emirati" and language is Arabic-led
(ar-AE or mixed). MSA, English, and non-Emirati items are left untouched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import text_normalize as tn

# ---------------------------------------------------------------------------
# Preferred Emirati lexical forms (generation + validation contract)
# ---------------------------------------------------------------------------
# Mapping: dispreferred / MSA-leaning → preferred Emirati.
# Used for prompts, detection, and (when safe) deterministic rewrites.

PREFERRED_EMIRATI_FORMS: list[tuple[str, str]] = [
    ("السابق", "اللي طاف"),
    ("الماضي", "اللي طاف"),
    ("أبغا", "ابا"),
    ("رجعت", "ردت"),
    ("انترنت", "نت"),
    ("عن قريب", "عقب شوي"),
    ("لمبة", "ليت"),
    ("تطفي", "تبند"),
    ("من غير", "من دون"),
    ("تغير", "تبدل"),
    ("أبكر", "من وقت"),
    ("بدري", "من وقت"),
    ("هلا بك", "مرحبا"),
    ("ظلت", "تمت"),
    ("عشان جي", "عسب جي"),
]


def preferred_forms_prompt_block() -> str:
    """Compact mapping block for system/user prompts."""
    lines = [
        "Emirati lexical consistency (mandatory when dialect=emirati):",
        "Prefer authentic UAE vocabulary. Avoid MSA / non-Emirati alternatives.",
        "Preferred mappings (use naturally; do not force if meaning would change):",
    ]
    for bad, good in PREFERRED_EMIRATI_FORMS:
        lines.append(f"  {bad} → {good}")
    lines.append(
        "When uncertain, keep the original meaning rather than an unnatural substitution."
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class LexicalIssue:
    rule: str
    match: str
    preferred: str
    start: int
    end: int
    safe_to_rewrite: bool = False


def _word(pattern: str) -> re.Pattern[str]:
    """Arabic-aware word boundary: not preceded/followed by an Arabic letter."""
    return re.compile(
        rf"(?<![ء-ي])(?:{pattern})(?![ء-ي])",
        re.IGNORECASE,
    )


_TEMPORAL_NOUN = (
    r"(الأ?سبوع|الشهر|اليوم|السنة|العام|الباقة|الفاتورة|الخطة|الاشتراك|"
    r"الرقم|الخط|العرض|الحساب)"
)
# Longer feminine forms first so السابقة/الماضية are not truncated to السابق/الماضي.
_TEMPORAL_ADJ = r"(الماضية|الماضي|السابقة|السابق)"
_TEMPORAL_RE = re.compile(rf"{_TEMPORAL_NOUN}\s+{_TEMPORAL_ADJ}")


def _temporal_preferred(noun: str, adj: str) -> str:
    """Gender-aware اللي طاف / اللي طافت after a concrete noun."""
    feminine = adj.endswith("ة") or noun.endswith("ة")
    return f"{noun} اللي طافت" if feminine else f"{noun} اللي طاف"


def _rewrite_temporal(match: re.Match[str]) -> str:
    return _temporal_preferred(match.group(1), match.group(2))


# Phrase rules: (name, pattern, preferred_label, rewrite_callable_or_string_or_None)
_PHRASE_RULES: list[tuple[str, re.Pattern[str], str, object | None]] = [
    ("an_qareeb", re.compile(r"عن\s+قريب"), "عقب شوي", "عقب شوي"),
    ("hala_bek", re.compile(r"هلا\s+بك"), "مرحبا", "مرحبا"),
    ("ashan_ji", re.compile(r"عشان\s+جي"), "عسب جي", "عسب جي"),
    ("min_ghair", re.compile(r"من\s+غير"), "من دون", "من دون"),
    (
        "al_madi_temporal",
        _TEMPORAL_RE,
        "اللي طاف",
        _rewrite_temporal,  # safe with gender agreement
    ),
]

_WORD_RULES: list[tuple[str, re.Pattern[str], str, str | None]] = [
    ("abgha", _word(r"أبغا|أبغى|أبغي|ابغا|ابغى|ابغي"), "ابا", "ابا"),
    ("rajaat", _word(r"رجعت|رجعتي|رجعنا"), "ردت", None),
    ("internet", _word(r"ال?انترنت|ال?إنترنت|انترنت|إنترنت|ال?انترنيت|انترنيت"), "نت", "نت"),
    ("lamba", _word(r"اللمبة|لمبة"), "ليت", None),
    ("titfi", _word(r"تطفي|تطفين|اطفي|طفي|طفيت|تطفئ|أطفئ|اطفئ"), "تبند", None),
    # "تغير" family is flagged for validation; not auto-rewritten (conjugation risk).
    ("taghayyar", _word(r"تغير|يتغير|تتغير|نغير|أغير|اغير|تغيرت"), "تبدل", None),
    ("abkar", _word(r"أبكر|ابكر"), "من وقت", "من وقت"),
    ("badri", _word(r"بدري"), "من وقت", "من وقت"),
    ("thallat", _word(r"ظلت|ظليت|ظلو"), "تمت", None),
    ("al_sabiq", _word(r"السابق|السابقة"), "اللي طاف", None),
    ("al_madi_bare", _word(r"الماضي|الماضية"), "اللي طاف", None),
]

# Idiomatic "في الماضي" / "بالماضي" — shared Arabic, do not treat as errors.
_MADI_IDIOM_RE = re.compile(r"(?:في|ب)\s*الماضي")


def is_emirati_arabic_item(dialect: str, language: str) -> bool:
    """True when Emirati lexical rules should run."""
    d = (dialect or "").strip().lower()
    lang = (language or "").strip()
    if d != "emirati":
        return False
    return lang in ("ar-AE", "mixed", "auto", "")


def find_dispreferred_forms(text: str) -> list[LexicalIssue]:
    """Return dispreferred Emirati lexical hits (detection only)."""
    if not text:
        return []
    issues: list[LexicalIssue] = []
    covered: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= a or start >= b) for a, b in covered)

    idiom_spans = [m.span() for m in _MADI_IDIOM_RE.finditer(text)]

    for name, pattern, preferred, rewrite in _PHRASE_RULES:
        for m in pattern.finditer(text):
            if _overlaps(m.start(), m.end()):
                continue
            issues.append(
                LexicalIssue(
                    name,
                    m.group(0),
                    preferred,
                    m.start(),
                    m.end(),
                    safe_to_rewrite=rewrite is not None,
                )
            )
            covered.append((m.start(), m.end()))

    for name, pattern, preferred, rewrite in _WORD_RULES:
        for m in pattern.finditer(text):
            if _overlaps(m.start(), m.end()):
                continue
            if name == "al_madi_bare" and any(
                not (m.end() <= a or m.start() >= b) for a, b in idiom_spans
            ):
                continue
            issues.append(
                LexicalIssue(
                    name,
                    m.group(0),
                    preferred,
                    m.start(),
                    m.end(),
                    safe_to_rewrite=rewrite is not None,
                )
            )
            covered.append((m.start(), m.end()))

    return issues


def _apply_rewrite(pattern: re.Pattern[str], rewrite: object, text: str) -> tuple[str, int]:
    if callable(rewrite):
        return pattern.subn(rewrite, text)
    return pattern.subn(str(rewrite), text)


def apply_safe_emirati_fixes(text: str) -> tuple[str, list[str]]:
    """Apply only meaning-safe deterministic rewrites.

    Unsafe / conjugation-sensitive mappings are left for rejection rather than
    rewrite. Returns (new_text, list of applied rule names).
    """
    if not text:
        return text, []
    applied: list[str] = []
    out = text
    for name, pattern, _preferred, rewrite in _PHRASE_RULES + _WORD_RULES:
        if rewrite is None:
            continue
        new_out, n = _apply_rewrite(pattern, rewrite, out)
        if n:
            applied.append(name)
            out = new_out
    return out, applied


def validate_emirati_lexicon(text: str) -> list[str]:
    """Return human-readable errors for remaining dispreferred forms."""
    return [
        f"Emirati lexical consistency: '{issue.match}' — prefer '{issue.preferred}' "
        f"(rule: {issue.rule})"
        for issue in find_dispreferred_forms(text)
    ]


def enforce_emirati_lexicon(
    display_text: str,
    training_text: str,
    *,
    dialect: str,
    language: str,
    apply_safe_fixes: bool = True,
) -> dict:
    """Post-generation Emirati lexical enforcement.

    Returns:
      {
        display_text, training_text,
        applied_fixes: [...],
        errors: [...],
        warnings: [...],
        applied: bool
      }

    Safe fixes rewrite unambiguous forms. Remaining dispreferred forms become
    hard errors (reject / regenerate) — never silently corrupted.
    """
    display = display_text or ""
    training = training_text or display
    result = {
        "display_text": display,
        "training_text": training,
        "applied_fixes": [],
        "errors": [],
        "warnings": [],
        "applied": False,
    }
    if not is_emirati_arabic_item(dialect, language):
        return result

    applied: list[str] = []
    if apply_safe_fixes:
        training, applied_t = apply_safe_emirati_fixes(training)
        display, applied_d = apply_safe_emirati_fixes(display)
        applied = sorted(set(applied_t) | set(applied_d))
        if applied:
            result["warnings"].append(
                "applied safe Emirati lexical fixes: " + ", ".join(applied)
            )

    errors = validate_emirati_lexicon(training)
    result.update(
        {
            "display_text": display,
            "training_text": training,
            "applied_fixes": applied,
            "errors": errors,
            "applied": True,
        }
    )
    return result


# ---------------------------------------------------------------------------
# Gender consistency (mandatory when speaker_gender is male|female)
# ---------------------------------------------------------------------------

SPEAKER_GENDERS = ("any", "male", "female")

_GENDER_ALIASES = {
    "any": "any",
    "unspecified": "any",
    "none": "any",
    "neutral": "any",
    "male": "male",
    "m": "male",
    "man": "male",
    "masculine": "male",
    "female": "female",
    "f": "female",
    "woman": "female",
    "feminine": "female",
}

# Feminine friend-group / relationship forms that conflict with a male speaker.
_FEMININE_FRIEND_RE = _word(r"ربيعاتي|ربعاتي|ربيعآتي|ربعآتي|صديقاتي|زميلاتي")
_MASCULINE_FRIEND_RE = _word(r"ربعي|ربعاي")

# Explicit masculine self-reference / address cues.
_MASCULINE_SELF_RE = re.compile(
    r"(?<![ء-ي])(?:"
    r"يا\s+خوي|يا\s+ولد|يا\s+رجال|"
    r"أنا\s+رجل|أنا\s+رجال|أنا\s+ولد|أنا\s+شاب"
    r")(?![ء-ي])"
)

# Explicit feminine self-reference cues (speaker presents as female).
_FEMININE_SELF_RE = re.compile(
    r"(?<![ء-ي])(?:"
    r"يا\s+بنت|يا\s+اختي|يا\s+ختي|"
    r"أنا\s+بنت|أنا\s+بنتكم|أنا\s+موظفة|أنا\s+زبونة"
    r")(?![ء-ي])"
)


def normalize_speaker_gender(value: object | None) -> str:
    """Normalize API/UI gender values to any | male | female."""
    if value is None:
        return "any"
    raw = str(value).strip().lower()
    if not raw:
        return "any"
    return _GENDER_ALIASES.get(raw, raw if raw in SPEAKER_GENDERS else "any")


def speaker_gender_prompt_label(value: object | None) -> str:
    """Human-readable gender label for prompts."""
    gender = normalize_speaker_gender(value)
    if gender == "any":
        return "any / not specified"
    return gender


def speaker_gender_prompt_block(value: object | None) -> str:
    """Mandatory speaker-gender instructions for the user prompt."""
    gender = normalize_speaker_gender(value)
    lines = [
        "Speaker gender — MANDATORY for this entire batch:",
        f"  speaker_gender = {speaker_gender_prompt_label(gender)}",
    ]
    if gender == "male":
        lines.extend(
            [
                "  Use masculine self-reference and relationship terms consistently.",
                "  Prefer ربعي (not ربيعاتي). Do not generate feminine self-forms.",
                "  Do not switch to female-speaker wording in any item.",
            ]
        )
    elif gender == "female":
        lines.extend(
            [
                "  Use feminine forms naturally where grammatically appropriate.",
                "  ربيعاتي is allowed when referring to female friends.",
                "  Do not switch to male-speaker self-reference in any item.",
            ]
        )
    else:
        lines.append(
            "  No gender constraint — do not invent or randomly switch speaker gender."
        )
    return "\n".join(lines)


def resolve_speaker_gender(
    item: dict,
    *,
    default_gender: str | None = None,
) -> str:
    """Resolve intended speaker gender.

    When the batch request sets speaker_gender to male or female, that value is
    mandatory for every utterance — no per-item inference or switching.

    Only when the batch gender is "any" may item tags / explicit cues refine it.
    """
    batch_gender = normalize_speaker_gender(default_gender)
    if batch_gender in ("male", "female"):
        return batch_gender

    raw = item.get("speaker_gender") or item.get("gender") or "any"
    gender = normalize_speaker_gender(raw)

    tags = [str(t).lower() for t in (item.get("tags") or [])]
    if gender == "any":
        if any(t in ("masculine", "gender:masculine", "male", "gender:male") for t in tags):
            gender = "male"
        elif any(t in ("feminine", "gender:feminine", "female", "gender:female") for t in tags):
            gender = "female"

    text = (item.get("training_text") or item.get("display_text") or "")
    if gender == "any" and _MASCULINE_SELF_RE.search(text):
        gender = "male"
    if gender == "any" and _FEMININE_SELF_RE.search(text):
        gender = "female"
    return gender


def validate_gender_consistency(
    text: str,
    *,
    speaker_gender: str = "any",
) -> list[str]:
    """Flag speaker-gender mismatches. Does not rewrite.

    male → reject feminine friend/self forms such as ربيعاتي
    female → reject explicit masculine self-reference
    any → only reject clear internal contradictions
    """
    if not text:
        return []
    errors: list[str] = []
    gender = normalize_speaker_gender(speaker_gender)
    has_fem_friends = bool(_FEMININE_FRIEND_RE.search(text))
    has_masc_self = bool(_MASCULINE_SELF_RE.search(text))
    has_fem_self = bool(_FEMININE_SELF_RE.search(text))

    if gender == "male":
        if has_fem_friends:
            errors.append(
                "Speaker gender (male): feminine friend form "
                "(e.g. 'ربيعاتي') — prefer masculine 'ربعي'"
            )
        if has_fem_self:
            errors.append(
                "Speaker gender (male): feminine self-reference is inconsistent "
                "with male speaker"
            )
    elif gender == "female":
        if has_masc_self:
            errors.append(
                "Speaker gender (female): masculine self-reference "
                "(e.g. 'أنا رجل' / 'يا ولد') is inconsistent with female speaker"
            )
    else:
        if has_masc_self and has_fem_friends:
            errors.append(
                "utterance has masculine cues but feminine friend form "
                "('ربيعاتي') — prefer 'ربعي'"
            )
        if has_masc_self and has_fem_self:
            errors.append(
                "utterance mixes masculine and feminine self-reference"
            )
    return errors


# ---------------------------------------------------------------------------
# Comparison fingerprint (dedup only — never stored)
# ---------------------------------------------------------------------------

_FINGERPRINT_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"عن\s+قريب"), "عقب_شوي"),
    (re.compile(r"عقب\s+شوي"), "عقب_شوي"),
    (re.compile(r"هلا\s+بك"), "مرحبا"),
    (re.compile(r"عشان\s+جي"), "عسب_جي"),
    (re.compile(r"عسب\s+جي"), "عسب_جي"),
    (re.compile(r"من\s+غير"), "من_دون"),
    (re.compile(r"من\s+دون"), "من_دون"),
    (
        re.compile(
            r"(الا?سبوع|الشهر|اليوم|السنه|العام|الباقه|الفاتوره|الخطه|الاشتراك)"
            r"\s+(الماضي|الماضيه|السابق|السابقه|اللي\s+طاف|اللي\s+طافت)"
        ),
        r"\1 اللي_طاف",
    ),
    (_word(r"ابغا|ابغى|ابغي|ابا|ابي|ابى|اريد"), "WANT"),
    (_word(r"اشيك|اتحقق|اشوف"), "CHECK"),
    (_word(r"ال?انترنت|ال?انترنيت|انترنت|انترنيت|النت|نت"), "NET"),
    (_word(r"الباقه|باقه"), "PACKAGE"),
    (_word(r"علي|على|من|عن|في"), "PREP"),
    (_word(r"رجعت|رجعتي|رجعنا|ردت|ردتي|ردنا"), "RETURNED"),
    (_word(r"اللمبه|لمبه|الليت|ليت"), "LIGHT"),
    (_word(r"تطفي|تطفين|اطفي|طفي|تبند|بند"), "SWITCH_OFF"),
    (_word(r"تغير|يتغير|تتغير|تبدل|يتبدل|تتبدل"), "CHANGE"),
    (_word(r"ابكر|بدري|من\s+وقت"), "EARLY"),
    (_word(r"ظلت|ظليت|تمت|تم"), "REMAINED"),
    (_word(r"ربيعاتي|ربعاتي|ربعي|ربعاي"), "FRIENDS"),
]


_FINGERPRINT_TIME_HALF_RE = re.compile(
    r"\b(واحد|اثنين|ثلاث|اربع|خمس|ست|سبع|ثمان|تمان|تسع|عشر)\s*(?:و)?(?:نص|نصف)\b"
)
_FINGERPRINT_TIME_COLON_RE = re.compile(r"\b(\d+)\s*:\s*30\b")
_FINGERPRINT_AR_NUM_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:واحد|واحده|وحده)\b"), "NUM1"),
    (re.compile(r"\b(?:اثنين|اثنان|ثنتين|ثنتان)\b"), "NUM2"),
    (re.compile(r"\b(?:ثلاث|ثلاثه|تلات|تلاته)\b"), "NUM3"),
    (re.compile(r"\b(?:اربعه|اربع|أربعة|أربع)\b"), "NUM4"),
    (re.compile(r"\b(?:خمس|خمسه)\b"), "NUM5"),
    (re.compile(r"\b(?:سته|ست|ستة|ست)\b"), "NUM6"),
    (re.compile(r"\b(?:سبعه|سبع|سبعة)\b"), "NUM7"),
    (re.compile(r"\b(?:ثمان|ثمانيه|ثمانية|تمان|تمانيه|تمانية)\b"), "NUM8"),
    (re.compile(r"\b(?:تسعه|تسع|تسعة)\b"), "NUM9"),
    (re.compile(r"\b(?:عشر(?:ه|ة)?)\b"), "NUM10"),
]


def emirati_fingerprint(text: str) -> str:
    """Normalize + collapse Emirati synonym variants for near-dup scoring."""
    # Unify digit clock times (9:30) with spoken half-hour forms (تسع ونص).
    t = _FINGERPRINT_TIME_COLON_RE.sub(r" \1 ونص ", text)
    t = tn.normalize_arabic(t, digits_to_words=True)
    t = _FINGERPRINT_TIME_HALF_RE.sub(
        lambda m: {
            "واحد": "NUM1",
            "اثنين": "NUM2",
            "ثلاث": "NUM3",
            "اربع": "NUM4",
            "خمس": "NUM5",
            "ست": "NUM6",
            "سبع": "NUM7",
            "ثمان": "NUM8",
            "تمان": "NUM8",
            "تسع": "NUM9",
            "عشر": "NUM10",
        }.get(m.group(1), m.group(1)) + " TIME_HALF",
        t,
    )
    # num2words may emit trailing 30 for former 9:30 patterns.
    t = re.sub(r"NUM9\s+(?:ثلاث(?:ون|ين|ه)?|30)\b", "NUM9 TIME_HALF", t)
    t = re.sub(r"\b(?:و)?(?:نص|نصف)\b", "TIME_HALF", t)
    for pattern, repl in _FINGERPRINT_AR_NUM_WORDS:
        t = pattern.sub(repl, t)
    for pattern, repl in _FINGERPRINT_SUBS:
        t = pattern.sub(repl, t)
    return tn.normalize_arabic(t)

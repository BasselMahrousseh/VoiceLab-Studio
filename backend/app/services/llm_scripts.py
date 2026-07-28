"""LLM-based multilingual script generation with governance validation.

Flow: generate → validate (charset, duplicates, policy rules) → human previews
flagged items in the UI → selected items are imported into the script bank.
Nothing generated is ever auto-imported.
"""
from __future__ import annotations

import json
import re

from rapidfuzz import fuzz

from ..config import Settings
from ..models import DIALECTS, DOMAINS, LANGUAGES, STYLES
from . import text_normalize as tn

SYSTEM_PROMPT = """You write recordable contact-center utterances for e& UAE voice
datasets (ASR/TTS training). Each item is one natural spoken turn a human will
read aloud — customer or agent — from a real telecom conversation.

Generation distribution:
Approximately 75% of the batch should be realistic telecom and customer-service
speech. Approximately 25% should be natural everyday Emirati speech unrelated
to telecom, such as greetings, family, friends, work, school, university,
shopping, restaurants, coffee, weather, traffic, driving, hobbies, sports,
travel, appointments, daily routines, health, celebrations, directions, and
polite social conversation. These non-telecom items must still sound authentic,
recordable, and natural for UAE speakers.

Domain (distribute across the batch; do not collapse into one scenario):
Customer care, billing & invoices, payments, VAT, technical support, mobile
data, voice calls, SMS, SIM/eSIM, roaming, internet, eLife, WiFi, router,
fiber, sales, offers/promotions, upgrades/downgrades, renewals, activation,
cancellation, complaints, service requests, account management, identity
verification, OTP, delivery/installation appointments, network coverage,
signal issues, slow internet, mobile-app support, and digital self-service.

Real-world scenario coverage:
Distribute generated utterances across realistic telecom situations rather than
generic requests only. Cover scenarios such as paying or checking a bill,
remaining balance, topping up credit, activating or cancelling a package,
upgrading or downgrading plans, eLife installation appointments, router or
WiFi troubleshooting, slow internet complaints, mobile data not working, SIM
or eSIM activation, roaming before travel, OTP or identity verification,
delivery scheduling, changing account information, reporting outages, 5G
coverage questions, Freedom plan questions, e& UAE App assistance, E&Money
transactions, VAT questions, payment confirmation, sales inquiries,
promotional offers, service cancellation, complaint handling, follow-up after
support, thanking the customer, and apologizing for inconvenience. Generate
scenes from both the customer and the agent perspective.

Utterance mix (balance; avoid request-only batches):
questions, statements, confirmations, greetings, complaints, acknowledgements,
agent responses, customer responses, polite exchanges, and short troubleshooting
guidance. Vary who is speaking and what they are doing.

Lexical & structural diversity:
Vary openings, verbs, and sentence shapes. No repeated templates or near-paraphrases
of the same line. In larger batches (about 30–100), spread topics and intents;
do not cluster on one journey.

Approved telecom terms (use naturally when relevant; never force into every line):
e&, eLife, e& UAE App, E&Money, Freedom, Freedom Life, 5G, WiFi, Fiber, SIM,
eSIM, roaming, package, data, recharge, balance, invoice, VAT. Prefer official
spellings from the request's brand list when one is provided.

Language behavior:
- When dialect is emirati: authentic UAE Emirati as spoken (Abu Dhabi/Dubai/
  Sharjah). Do not rewrite into MSA or other Arabic dialects.
- English must sound native and stay English when English is requested.
- Code-switch only when asked or when mixed language is in scope — natural
  contact-center mixing, not forced.

Recordability:
One complete breath-sized utterance per item. Tag every item with language
(ar-AE | en-US | mixed) and dialect (emirati | msa | english | mixed). Provide
display_text and training_text; if they need no change, make them identical.
Follow the administrator text policy appended after this message for orthography,
numbers, brands, and transcript formatting.

JSON only — no prose outside the object:
{"items": [{"display_text": "...", "training_text": "...", "msa_equivalent": null, "language": "ar-AE", "style": "...", "domain": "...", "dialect": "...", "tags": ["..."], "note": ""}]}
"""


COVERAGE_HINTS = {
    "numbers": "أرقام وكميات (فواتير، جيجابايت، دقائق، نسب مئوية)",
    "dates_times": "تواريخ وأوقات (اليوم، بكرة، الساعة 5، 15 مارس، نهاية الشهر)",
    "prices": "أسعار ومبالغ بالدرهم (99 درهم، 149.50، ضريبة 5%)",
    "id_codes": "أرقام هواتف وحسابات وأكواد تُقرأ رقماً رقماً (050، رمز التحقق 4482)",
    "code_switch": "دمج إنجليزي-عربي طبيعي (code-switching)",
    "brands": "أسماء علامات وخدمات وتقنيات",
}


def build_user_prompt(params: dict, settings: Settings) -> str:
    count = int(params.get("count", 20))
    styles = params.get("styles") or ["neutral"]
    domains = params.get("domains") or ["customer_support"]
    languages = params.get("languages") or ["ar-AE"]
    dialect = params.get("dialect") or "emirati"
    lengths = params.get("length_mix") or ["short", "medium", "long"]
    coverage = params.get("coverage") or []
    topics = (params.get("topics") or "").strip()
    brands = (params.get("brand_terms") or "").strip()

    lines = [
        f"أنشئ {count} جملة.",
        f"الأساليب المطلوبة (وزّع عليها): {', '.join(styles)}",
        f"المجالات: {', '.join(domains)}",
        f"Languages (distribute across exactly these): {', '.join(languages)}",
        f"اللهجة: {dialect}"
        + (" (مزيج طبيعي بين الإماراتية والفصحى)" if dialect == "mixed" else ""),
        f"أطوال الجمل (وزّع): {', '.join(lengths)}",
    ]
    avg_duration = float(params.get("avg_duration_sec") or 0)
    if avg_duration > 0:
        wps = getattr(settings, "llm_words_per_second", 2.3) or 2.3
        target_words = max(2, round(avg_duration * wps))
        lines.append(
            f"استهدف أن تستغرق قراءة كل جملة حوالي {avg_duration:.0f} ثانية عند القراءة الطبيعية "
            f"(أي بحدود {target_words} كلمة لكل جملة تقريباً)."
        )
    if coverage:
        lines.append("غطِّ هذه الأنواع ضمن الجمل: "
                     + "؛ ".join(COVERAGE_HINTS.get(c, c) for c in coverage))
    if brands:
        lines.append(f"أسماء العلامات/المصطلحات المسموح استخدامها: {brands}")
    if topics:
        lines.append(f"مواضيع أو سيناريوهات مقترحة: {topics}")
    if languages == ["ar-AE"]:
        lines.extend([
            "مهم جداً: كل جملة موسومة ar-AE يجب أن تكون عربية بالكامل.",
            "ممنوع أي كلمات إنجليزية أو أحرف لاتينية أو code-switching داخل جمل ar-AE.",
            "إذا احتاج المعنى كلمة إنجليزية أو اسم منتج غير معرّب، لا تضعها ضمن ar-AE بل اعتبرها mixed.",
            "استخدم فقط أسماء المنتجات أو المصطلحات إذا كانت لها صيغة عربية طبيعية ومكتوبة بالعربية.",
        ])
    elif "ar-AE" in languages:
        lines.extend([
            "أي عنصر موسوم ar-AE يجب أن يكون عربياً بالكامل بلا أحرف لاتينية.",
            "أي عنصر يحتوي إنجليزية أو أسماء منتجات لاتينية يجب وسمه mixed وليس ar-AE.",
        ])
    lines.append(
        "Return JSON only. Tag every item with language. Numbers in training_text "
        "must be written as spoken words in that item's language."
    )
    return "\n".join(lines)


def _client(settings: Settings, api_style: str = "chat"):
    if settings.llm_provider == "azure":
        from openai import AzureOpenAI, OpenAI

        if api_style == "responses":
            # Azure's current Responses API is exposed through the OpenAI v1
            # route, not the legacy deployment + api-version route constructed
            # by AzureOpenAI.
            base_url = f"{settings.azure_openai_endpoint.rstrip('/')}/openai/v1/"
            if settings.azure_openai_api_key:
                api_key = settings.azure_openai_api_key
            else:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider

                credential = DefaultAzureCredential(
                    managed_identity_client_id=settings.azure_client_id or None,
                    exclude_interactive_browser_credential=True,
                )
                api_key = get_bearer_token_provider(
                    credential, "https://ai.azure.com/.default"
                )
            return OpenAI(base_url=base_url, api_key=api_key)

        kwargs = {
            "azure_endpoint": settings.azure_openai_endpoint,
            "api_version": settings.azure_openai_api_version,
        }
        if settings.azure_openai_api_key:
            kwargs["api_key"] = settings.azure_openai_api_key
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
        base_url=settings.openai_base_url or None,
        api_key=settings.openai_api_key or "not-needed",
    )


def _extract_json(text: str) -> dict:
    """Parse LLM output that may be wrapped in code fences or prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _max_output_tokens(count: int) -> int:
    # Room for the JSON payload plus (for reasoning models) hidden reasoning.
    return min(32000, 2000 + count * 220)


def _generate_via_responses(client, settings: Settings, messages: list[dict], count: int) -> str:
    """Azure/OpenAI Responses API (gpt-5.x and other newer models)."""
    resp = client.responses.create(
        model=settings.llm_deployment,
        input=messages,
        max_output_tokens=_max_output_tokens(count),
    )
    return getattr(resp, "output_text", "") or ""


def _generate_via_chat(client, settings: Settings, messages: list[dict]) -> str:
    """Classic Chat Completions API. Degrade gracefully on unsupported params."""
    kwargs: dict = {"model": settings.llm_deployment, "messages": messages}
    for attempt in (
        {"temperature": 1.0, "response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_object"}},
        {},
    ):
        try:
            resp = client.chat.completions.create(**kwargs, **attempt)
            return resp.choices[0].message.content or ""
        except Exception:
            continue
    # Re-raise the final failure for the caller to surface.
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def generate_scripts(params: dict, settings: Settings) -> list[dict]:
    """Call the configured LLM deployment and return raw generated items."""
    policy = (params.get("policy_text") or "").strip()
    system_prompt = SYSTEM_PROMPT
    if policy:
        system_prompt += (
            "\n\nThe following administrator-authored text policy is mandatory. "
            "Follow it in addition to the structural rules above:\n\n" + policy
        )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_prompt(params, settings)},
    ]
    count = int(params.get("count", 20))
    style = getattr(settings, "llm_api_style", "auto")

    if style == "chat":
        client = _client(settings, "chat")
        content = _generate_via_chat(client, settings, messages)
    elif style == "responses":
        client = _client(settings, "responses")
        content = _generate_via_responses(client, settings, messages, count)
    else:  # auto: prefer Responses (needed by gpt-5.x), fall back to Chat
        try:
            client = _client(settings, "responses")
            content = _generate_via_responses(client, settings, messages, count)
        except Exception:
            client = _client(settings, "chat")
            content = _generate_via_chat(client, settings, messages)

    data = _extract_json(content)
    items = data.get("items", data if isinstance(data, list) else [])
    if not isinstance(items, list):
        raise ValueError("LLM response did not contain an items list")
    return items


# ---------------------------------------------------------------------------
# Validation (also used for manual imports)
# ---------------------------------------------------------------------------
# Characters allowed in transcripts: Arabic block, ASCII letters/digits,
# common punctuation. Anything else is flagged for review.
_ALLOWED_RE = re.compile(
    "[^؀-ۿ0-9A-Za-z\\s"
    ".,!?;:%()\\-،؛؟٪“”'\"/+&@#*–—×]"
)

NEAR_DUP_THRESHOLD = 92  # rapidfuzz token_sort_ratio


def detect_language(text: str) -> str:
    has_arabic = bool(re.search(r"[\u0600-\u06ff]", text))
    has_latin = tn.has_latin(text)
    if has_arabic and has_latin:
        return "mixed"
    if has_latin:
        return "en-US"
    return "ar-AE"


def validate_item(
    item: dict,
    existing_hashes: set[str],
    existing_texts: list[str],
    batch_hashes: set[str],
) -> dict:
    """Return {ok, errors, warnings, computed} for one candidate script."""
    errors: list[str] = []
    warnings: list[str] = []

    display = (item.get("display_text") or "").strip()
    training = (item.get("training_text") or display).strip()
    requested_language = (item.get("language") or "auto").strip()
    detected_language = detect_language(training or display)
    language = (
        detected_language
        if requested_language == "auto" or requested_language not in LANGUAGES
        else requested_language
    )

    if not display:
        errors.append("empty display_text")
    if not training:
        errors.append("empty training_text")

    if training:
        if tn.has_digits(training):
            errors.append("digits in training_text (policy: numbers must be written as words)")
        bad = set(_ALLOWED_RE.findall(display + " " + training))
        if bad:
            errors.append(f"disallowed characters: {' '.join(sorted(bad))}")
        if requested_language == "ar-AE" and (
            tn.has_latin(display) or tn.has_latin(training) or detected_language != "ar-AE"
        ):
            errors.append("ar-AE items must be fully Arabic with no English words, Latin script, or code-switching")
        if requested_language == "en-US" and detected_language != "en-US":
            errors.append("en-US items must be fully English with no Arabic script")
        if language == "ar-AE" and tn.arabic_ratio(training) < 0.5:
            warnings.append("less than half the text is Arabic - check dialect/code-switch tag")

        h = tn.normalized_hash(training)
        if h in existing_hashes:
            errors.append("exact duplicate of an existing script")
        elif h in batch_hashes:
            errors.append("duplicate within this batch")
        else:
            norm = tn.normalize_arabic(training)
            for other in existing_texts:
                if fuzz.token_sort_ratio(norm, other) >= NEAR_DUP_THRESHOLD:
                    warnings.append("near-duplicate of an existing script")
                    break
        batch_hashes.add(h)

    style = (item.get("style") or "neutral").strip().lower()
    domain = (item.get("domain") or "general").strip().lower()
    dialect = (item.get("dialect") or "emirati").strip().lower()
    if language == "en-US":
        dialect = "english"
    elif language == "mixed":
        dialect = "mixed"
    if style not in STYLES:
        warnings.append(f"unknown style '{style}'")
    if domain not in DOMAINS:
        warnings.append(f"unknown domain '{domain}'")
    if dialect not in DIALECTS:
        warnings.append(f"unknown dialect '{dialect}'")

    tags = list(item.get("tags") or [])
    if language == "mixed" and "code_switch" not in tags:
        tags = [*tags, "code_switch"]
    if tn.has_digits(display) and "numbers" not in tags:
        tags = [*tags, "numbers"]
    language_tag = f"language:{language}"
    if language_tag not in tags:
        tags = [*tags, language_tag]

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "computed": {
            "display_text": display,
            "training_text": training,
            "msa_equivalent": (item.get("msa_equivalent") or None),
            "language": language,
            "style": style,
            "domain": domain,
            "dialect": dialect,
            "tags": tags,
            "note": item.get("note") or "",
            "length_bucket": tn.length_bucket(training),
            "word_count": tn.word_count(training),
            "char_count": len(training),
        },
    }

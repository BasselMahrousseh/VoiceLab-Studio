"""LLM-based script generation with Arabic/Emirati governance validation.

Flow: generate → validate (charset, duplicates, policy rules) → human previews
flagged items in the UI → selected items are imported into the script bank.
Nothing generated is ever auto-imported.
"""
from __future__ import annotations

import json
import re

from rapidfuzz import fuzz

from ..config import Settings
from ..models import DIALECTS, DOMAINS, STYLES
from . import text_normalize as tn

SYSTEM_PROMPT = """أنت كاتب نصوص محترف متخصص باللهجة الإماراتية، تجهّز جمل تسجيل لبناء داتاسيت صوتي إماراتي عالي الجودة (لتدريب نموذج تحويل نص إلى كلام). متحدث واحد سيقرأ كل جملة بصوت طبيعي.

قواعد إلزامية:
1. اكتب باللهجة الإماراتية الأصيلة (أبوظبي/دبي/الشارقة) عندما يكون المطلوب "emirati": استخدم مفردات مثل: شو، وايد، عيل، تبا/تبغي، جذي، الحين، يالس، شحالك، مب، عسب، يوم (بمعنى لما)... تجنّب مفردات لهجات أخرى (مصرية، شامية، سعودية نجدية) إلا إذا طُلبت.
2. لا تحوّل الجمل الإماراتية إلى فصحى. النص يُكتب كما يُنطق تماماً.
3. بدون تشكيل (إلا إذا لزم لتوضيح لبس نادر).
4. الجمل يجب أن تكون طبيعية وقابلة للقراءة بنفس واحد، مناسبة للتسجيل الصوتي.
5. لكل جملة أعطِ حقلين للنص:
   - display_text: ما يُعرض على القارئ (يمكن أن يحتوي أرقاماً مثل 24 أو كلمات إنجليزية مثل SIM).
   - training_text: النطق الحرفي الكامل — الأرقام تُكتب كلمات عربية كما ستُنطق باللهجة (مثال: "24" تصبح "أربعة وعشرين")، والكلمات الإنجليزية تبقى بالحروف اللاتينية كما ستُنطق. إذا لم يكن هناك أرقام أو رموز، يكون training_text مطابقاً لـ display_text.
6. عند طلب code-switching: ادمج كلمات إنجليزية شائعة في كلام الإماراتيين (باقة، داتا، نت، رصيد مع: package, data, roaming, offer, app, SIM, upgrade...) بشكل طبيعي غير متكلف.
7. msa_equivalent: أضف المعادل بالفصحى فقط إذا كانت الجملة لهجة (اختياري، للميتاداتا وليس للتدريب).
8. نوّع طول الجمل حسب المطلوب: short (2-5 كلمات)، medium (6-14 كلمة)، long (15-25 كلمة).
9. لا تكرر الصيغ ولا القوالب. كل جملة مختلفة فعلاً في التركيب والموضوع.

أعد النتيجة بصيغة JSON فقط بدون أي نص آخر:
{"items": [{"display_text": "...", "training_text": "...", "msa_equivalent": null, "style": "...", "domain": "...", "dialect": "...", "tags": ["..."], "note": ""}]}
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
    styles = params.get("styles") or ["neutral", "friendly"]
    domains = params.get("domains") or ["customer_support"]
    dialect = params.get("dialect") or "emirati"
    lengths = params.get("length_mix") or ["short", "medium", "long"]
    coverage = params.get("coverage") or []
    topics = (params.get("topics") or "").strip()
    brands = (params.get("brand_terms") or "").strip()

    lines = [
        f"أنشئ {count} جملة.",
        f"الأساليب المطلوبة (وزّع عليها): {', '.join(styles)}",
        f"المجالات: {', '.join(domains)}",
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
    lines.append("تذكّر: JSON فقط بالصيغة المحددة، والأرقام في training_text تُكتب كلمات.")
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
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
        if tn.arabic_ratio(training) < 0.5 and "code_switch" not in (item.get("tags") or []):
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
    if style not in STYLES:
        warnings.append(f"unknown style '{style}'")
    if domain not in DOMAINS:
        warnings.append(f"unknown domain '{domain}'")
    if dialect not in DIALECTS:
        warnings.append(f"unknown dialect '{dialect}'")

    tags = item.get("tags") or []
    if tn.has_latin(training) and "code_switch" not in tags:
        tags = [*tags, "code_switch"]
    if tn.has_digits(display) and "numbers" not in tags:
        tags = [*tags, "numbers"]

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "computed": {
            "display_text": display,
            "training_text": training,
            "msa_equivalent": (item.get("msa_equivalent") or None),
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

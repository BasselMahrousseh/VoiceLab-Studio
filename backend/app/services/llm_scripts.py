"""LLM-based multilingual script generation with governance validation.

Flow: plan scenarios → generate → validate (charset, Emirati lexicon, gender,
duplicates, policy rules) → human previews flagged items in the UI → selected
items are imported into the script bank. Nothing generated is ever auto-imported.
"""
from __future__ import annotations

import json
import re

from rapidfuzz import fuzz

from ..config import Settings
from ..models import DIALECTS, DOMAINS, LANGUAGES, STYLES
from . import emirati_dialect as emirati
from . import scenario_planner
from . import text_normalize as tn

SYSTEM_PROMPT = """You write recordable contact-center utterances for e& UAE voice
datasets (ASR/TTS training). Each item is one natural spoken turn a human will
read aloud — customer or agent — from a real telecom conversation.

Generation distribution:
The user prompt specifies EXACT counts: a number of telecom/domain sentences and
a number of general everyday sentences. You MUST honour those exact counts.
- Telecom/domain sentences: tag with the appropriate domain from the request list.
- General everyday sentences: MUST be tagged domain="general". Topics: greetings,
  family, friends, work, school, university, shopping, restaurants, coffee,
  weather, traffic, driving, hobbies, sports, travel, appointments, daily
  routines, health, celebrations, directions, polite social conversation.
  These must sound authentic, recordable, and natural for UAE speakers.
  Do NOT tag everyday sentences as customer_support, telecom, billing, or any
  other telecom domain.

Domain (distribute across the batch; do not collapse into one scenario):
Customer care, billing & invoices, payments, VAT, technical support, mobile
data, voice calls, SMS, SIM/eSIM, roaming, internet, eLife, WiFi, router,
fiber, sales, offers/promotions, upgrades/downgrades, renewals, activation,
cancellation, complaints, service requests, account management, identity
verification, OTP, delivery/installation appointments, network coverage,
signal issues, slow internet, mobile-app support, digital self-service, and
HR/workplace topics (leave, payroll, attendance, benefits, onboarding,
employment letters, training, work-from-home).

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
support, thanking the customer, and apologizing for inconvenience. Also cover
HR/workplace situations: annual or sick leave, leave balance, payroll issues,
salary clarification, employment letters, updating employee information,
attendance corrections, manager communication, training registration, benefits
inquiries, and work-from-home requests — not only leave requests. Generate
scenes from both the customer and the agent perspective.

Utterance mix (balance; avoid request-only batches):
questions, statements, confirmations, greetings, complaints, acknowledgements,
agent responses, customer responses, polite exchanges, and short troubleshooting
guidance. Vary who is speaking and what they are doing.

Lexical & structural diversity:
Vary openings, verbs, and sentence shapes. No repeated templates or near-paraphrases
of the same line. In larger batches (about 30–100), spread topics and intents;
do not cluster on one journey. Follow the numbered scenario plan in the user
prompt exactly — one distinct scenario per item.

Scenario diversity (mandatory — domain spread alone is NOT enough):
Generation hierarchy: Domain → Scenario → Intent → Utterance.
Each item must represent a distinct real-world scenario, customer intent, or
conversational situation. Do not generate multiple utterances from the same
scenario unless explicitly requested. Do not create near-paraphrases of another
item. Vary customer journeys, problems, requests, responses, and outcomes.
For batches of 20+, use multiple distinct scenarios within each domain.
Do not repeatedly reuse the same sentence structure, opening, request pattern,
or conversational flow. Tag every item with scenario:<scenario_id> matching
the plan. General (~25%) must be non-telecom daily life: friends, family,
workplace, shopping, restaurants, travel, appointments, transportation.
Business/telecom (~75%) covers contact-center and workplace scenarios.

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

Emirati lexical consistency (mandatory when dialect=emirati):
Prefer authentic UAE vocabulary. Avoid MSA or non-Emirati alternatives.
Preferred mappings (use naturally according to grammar/context; do not force
when meaning would change):
  السابق → اللي طاف
  الماضي → اللي طاف
  أبغا → ابا
  رجعت → ردت
  انترنت → نت
  عن قريب → عقب شوي
  لمبة → ليت
  تطفي → تبند
  من غير → من دون
  تغير → تبدل
  أبكر → من وقت
  بدري → من وقت
  هلا بك → مرحبا
  ظلت → تمت
  عشان جي → عسب جي
When uncertain, preserve the original meaning rather than an unnatural
substitution. Post-generation validation enforces these preferences.

Speaker gender — MANDATORY:
Follow the selected speaker_gender consistently throughout every utterance
in the batch. Do not infer or randomly switch speaker gender within a batch.
- If speaker_gender is "male": use masculine self-reference and relationship
  terms. Prefer ربعي; do NOT generate feminine forms such as ربيعاتي when
  masculine ربعي is intended. Do not use feminine self-reference.
- If speaker_gender is "female": use feminine forms naturally where
  grammatically appropriate (ربيعاتي is valid for female friends).
- If speaker_gender is "any": do not impose a gender constraint and do not
  invent a gender.
- Do not change grammatically valid wording that already matches the selected
  gender. Post-generation validation enforces these rules.

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


def ensure_scenario_plan(params: dict) -> list[dict]:
    """Attach a deterministic scenario plan to params if missing; return it."""
    existing = params.get("scenario_plan")
    if isinstance(existing, list) and existing:
        return existing
    count = int(params.get("count", 20))
    domains = params.get("domains") or [
        "customer_support", "telecom", "billing", "technical_support", "sales"
    ]
    include_general = params.get("include_general", True)
    if isinstance(include_general, str):
        include_general = include_general.strip().lower() not in ("0", "false", "no")
    speaker_gender = emirati.normalize_speaker_gender(params.get("speaker_gender"))
    params["speaker_gender"] = speaker_gender
    plan = scenario_planner.plan_as_dicts(
        scenario_planner.plan_generation_batch(
            count,
            domains=list(domains),
            include_general=bool(include_general),
            languages=list(params.get("languages") or ["ar-AE"]),
            dialect=str(params.get("dialect") or "emirati"),
            styles=list(params.get("styles") or ["neutral"]),
            speaker_gender=speaker_gender,
        )
    )
    params["scenario_plan"] = plan
    return plan


def _plan_slots(plan: list[dict]) -> list[scenario_planner.ScenarioSlot]:
    return [scenario_planner.slot_from_dict(s) for s in plan]


def format_scenario_assignment(slot: dict, *, item_number: int) -> str:
    """Render one ITEM block for the LLM user prompt."""
    domain_label = (slot.get("domain") or "general").replace("_", " ").title()
    gender = emirati.speaker_gender_prompt_label(slot.get("speaker_gender"))
    return "\n".join(
        [
            f"ITEM {item_number}",
            f"Domain: {domain_label}",
            f"Scenario: {slot.get('scenario')}",
            f"Intent: {slot.get('intent')}",
            f"Speaker: {slot.get('speaker_role', 'customer')}",
            f"Gender: {gender}",
            f"Language: {slot.get('language', 'ar-AE')}",
            f"Dialect: {slot.get('dialect', 'emirati')}",
            f"Style: {slot.get('style', 'neutral')}",
        ]
    )


SCENARIO_ASSIGNMENT_RULES = """\
Scenario assignment rules (mandatory):
- Generate exactly one utterance for each assigned ITEM above, in the same order.
- Do not swap scenarios between slots.
- Do not invent a different scenario.
- The utterance must clearly express the assigned intent.
- Keep the assigned domain, language, dialect, gender, and style.
- Do not mention the scenario id/name in the generated text.
- Do not generate multiple utterances for one scenario.
- Tag each item with scenario:<scenario_id> exactly matching the assignment."""


def build_user_prompt(params: dict, settings: Settings) -> str:
    count = int(params.get("count", 20))
    styles = params.get("styles") or ["neutral"]
    domains = params.get("domains") or [
        "customer_support", "telecom", "billing", "technical_support", "sales"
    ]
    languages = params.get("languages") or ["ar-AE"]
    dialect = params.get("dialect") or "emirati"
    lengths = params.get("length_mix") or ["short", "medium", "long"]
    coverage = params.get("coverage") or []
    topics = (params.get("topics") or "").strip()
    brands = (params.get("brand_terms") or "").strip()
    speaker_gender = emirati.normalize_speaker_gender(params.get("speaker_gender"))
    gender_label = emirati.speaker_gender_prompt_label(speaker_gender)

    plan = ensure_scenario_plan(params)
    plan_offset = int(params.get("plan_offset", 0))
    summary = scenario_planner.summarize_plan(_plan_slots(plan))
    telecom_count = summary["telecom"]
    general_count = summary["general"]

    lines = [
        f"Generate {count} utterances using the exact scenario assignments below.",
        f"Batch distribution: {telecom_count} telecom/business + {general_count} general.",
        f"Styles (rotate as assigned): {', '.join(styles)}",
        f"Languages (as assigned per item): {', '.join(languages)}",
        f"Default dialect: {dialect}"
        + (" (natural Emirati/MSA mix when language=mixed)" if dialect == "mixed" else ""),
        f"Length mix (rotate): {', '.join(lengths)}",
        f"Batch speaker gender: {gender_label}",
        "",
        "MANDATORY SCENARIO ASSIGNMENTS — one utterance per ITEM, same order:",
    ]
    for i, slot in enumerate(plan):
        lines.append("")
        lines.append(format_scenario_assignment(slot, item_number=plan_offset + i + 1))
    lines.append("")
    lines.append(SCENARIO_ASSIGNMENT_RULES)
    plan_issues = scenario_planner.validate_plan(_plan_slots(plan))
    if plan_issues:
        lines.append("تنبيه داخلي للخطة: " + "; ".join(plan_issues))
    hr_in_plan = any(s.get("domain") == "hr" for s in plan)
    if hr_in_plan:
        lines.append(
            "الخطة تتضمن جمل HR/workplace (domain=\"hr\") — "
            "اكتبها كمواقف عمل/موارد بشرية حقيقية (إجازة، راتب، حضور، تدريب، خطاب تعريف…) "
            "وليس كخدمة عملاء اتصالات."
        )
    if speaker_gender == "male":
        lines.append(emirati.speaker_gender_prompt_block("male"))
    elif speaker_gender == "female":
        lines.append(emirati.speaker_gender_prompt_block("female"))
    else:
        lines.append(emirati.speaker_gender_prompt_block("any"))
    if (dialect or "").strip().lower() == "emirati" and (
        "ar-AE" in languages or "mixed" in languages
    ):
        lines.append(emirati.preferred_forms_prompt_block())
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
        lines.append(f"مواضيع أو سيناريوهات مقترحة إضافية: {topics}")
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
    # Normalize once so retries / mini-batches keep a stable canonical value.
    params["speaker_gender"] = emirati.normalize_speaker_gender(
        params.get("speaker_gender")
    )
    ensure_scenario_plan(params)
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


MAX_ITEM_RETRIES = 2
_RETRYABLE_ERROR_MARKERS = (
    "scenario mismatch",
    "missing scenario tag",
    "domain mismatch",
    "style mismatch",
    "language mismatch",
    "dialect mismatch",
)


def is_retryable_validation(result: dict) -> bool:
    """True when a single-item regeneration may fix the failure."""
    if result.get("ok"):
        return False
    errors = result.get("errors") or []
    return any(any(m in e.lower() for m in _RETRYABLE_ERROR_MARKERS) for e in errors)


def build_retry_user_prompt(
    slot: dict,
    params: dict,
    settings: Settings,
    errors: list[str],
) -> str:
    """Prompt for regenerating one item that failed scenario/metadata validation."""
    item_no = int(slot.get("index", 0)) + 1
    err_text = "; ".join(errors[:5])
    lines = [
        "The previous utterance did not match the assigned scenario or metadata.",
        f"Validation errors: {err_text}",
        "",
        "Required assignment (do not change):",
        format_scenario_assignment(slot, item_number=item_no),
        "",
        f"Required scenario: {slot.get('scenario')}",
        f"Required intent: {slot.get('intent')}",
        "",
        "Generate a new utterance that clearly expresses this exact scenario and intent.",
        "Do not change the scenario, domain, language, dialect, gender, or style.",
        "Do not mention the scenario id/name in the generated text.",
        "Tag the item with scenario:<scenario_id> exactly matching the assignment.",
        "Return JSON only: {\"items\": [{...}]} with exactly one item.",
    ]
    speaker_gender = emirati.normalize_speaker_gender(
        slot.get("speaker_gender") or params.get("speaker_gender")
    )
    if speaker_gender == "male":
        lines.append(emirati.speaker_gender_prompt_block("male"))
    elif speaker_gender == "female":
        lines.append(emirati.speaker_gender_prompt_block("female"))
    dialect = (slot.get("dialect") or params.get("dialect") or "emirati").strip().lower()
    language = slot.get("language") or "ar-AE"
    if dialect == "emirati" and language in ("ar-AE", "mixed"):
        lines.append(emirati.preferred_forms_prompt_block())
    avg_duration = float(params.get("avg_duration_sec") or 0)
    if avg_duration > 0:
        wps = getattr(settings, "llm_words_per_second", 2.3) or 2.3
        target_words = max(2, round(avg_duration * wps))
        lines.append(
            f"Target ~{avg_duration:.0f}s spoken duration (~{target_words} words)."
        )
    return "\n".join(lines)


def _call_llm_messages(
    messages: list[dict],
    *,
    settings: Settings,
    count: int,
) -> str:
    """Shared LLM dispatch for full-batch and single-item regeneration."""
    style = getattr(settings, "llm_api_style", "auto")
    if style == "chat":
        client = _client(settings, "chat")
        return _generate_via_chat(client, settings, messages)
    if style == "responses":
        client = _client(settings, "responses")
        return _generate_via_responses(client, settings, messages, count)
    try:
        client = _client(settings, "responses")
        return _generate_via_responses(client, settings, messages, count)
    except Exception:
        client = _client(settings, "chat")
        return _generate_via_chat(client, settings, messages)


def regenerate_single_item(
    slot: dict,
    params: dict,
    settings: Settings,
    errors: list[str],
) -> dict:
    """Regenerate exactly one item for a fixed scenario slot."""
    policy = (params.get("policy_text") or "").strip()
    system_prompt = SYSTEM_PROMPT
    if policy:
        system_prompt += (
            "\n\nThe following administrator-authored text policy is mandatory. "
            "Follow it in addition to the structural rules above:\n\n" + policy
        )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": build_retry_user_prompt(slot, params, settings, errors),
        },
    ]
    content = _call_llm_messages(messages, settings=settings, count=1)
    data = _extract_json(content)
    items = data.get("items", data if isinstance(data, list) else [])
    if not isinstance(items, list) or not items:
        raise ValueError("LLM retry response did not contain an items list")
    return items[0]


def validate_planned_item(
    item: dict,
    slot: dict,
    *,
    existing_hashes: set[str],
    existing_texts: list[str],
    batch_hashes: set[str],
    batch_scenario_ids: set[str] | None = None,
    speaker_gender: str | None = None,
    apply_safe_lexical_fixes: bool = True,
) -> dict:
    """Validate one generated item against its planner slot."""
    gender = emirati.normalize_speaker_gender(
        speaker_gender or slot.get("speaker_gender") or "any"
    )
    return validate_item(
        item,
        existing_hashes,
        existing_texts,
        batch_hashes,
        speaker_gender=gender,
        apply_safe_lexical_fixes=apply_safe_lexical_fixes,
        batch_scenario_ids=batch_scenario_ids,
        expected_scenario=slot.get("scenario"),
        expected_slot=slot,
    )


def generate_validated_items(
    params: dict,
    settings: Settings,
    plan: list[dict],
    *,
    existing_hashes: set[str],
    existing_texts: list[str],
    batch_hashes: set[str],
    batch_scenario_ids: set[str] | None = None,
    max_retries: int = MAX_ITEM_RETRIES,
) -> list[dict]:
    """Generate items for a plan slice and retry failed slots individually."""
    speaker_gender = emirati.normalize_speaker_gender(params.get("speaker_gender"))
    params["speaker_gender"] = speaker_gender
    raw_items = generate_scripts(params, settings)
    results: list[dict] = []

    for i, slot in enumerate(plan):
        item = raw_items[i] if i < len(raw_items) else {}
        result = validate_planned_item(
            item,
            slot,
            existing_hashes=existing_hashes,
            existing_texts=existing_texts,
            batch_hashes=batch_hashes,
            batch_scenario_ids=batch_scenario_ids,
            speaker_gender=speaker_gender,
        )
        attempts = 0
        while not result["ok"] and attempts < max_retries and is_retryable_validation(result):
            try:
                item = regenerate_single_item(
                    slot, params, settings, result.get("errors") or []
                )
            except Exception as exc:
                result.setdefault("errors", []).append(
                    f"regeneration failed: {type(exc).__name__}: {exc}"
                )
                break
            result = validate_planned_item(
                item,
                slot,
                existing_hashes=existing_hashes,
                existing_texts=existing_texts,
                batch_hashes=batch_hashes,
                batch_scenario_ids=batch_scenario_ids,
                speaker_gender=speaker_gender,
            )
            attempts += 1
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Validation (also used for manual imports)
# ---------------------------------------------------------------------------
# Characters allowed in transcripts: Arabic block, ASCII letters/digits,
# common punctuation. Anything else is flagged for review.
_ALLOWED_RE = re.compile(
    "[^؀-ۿ0-9A-Za-z\\s"
    ".,!?;:%()\\-،؛؟٪“”'\"/+&@#*–—×]"
)

NEAR_DUP_THRESHOLD = 92  # rapidfuzz token_sort_ratio on normalized text
NEAR_DUP_FINGERPRINT_THRESHOLD = 90  # after Emirati synonym folding
NEAR_DUP_TOKEN_SET_THRESHOLD = 95


def detect_language(text: str) -> str:
    has_arabic = bool(re.search(r"[\u0600-\u06ff]", text))
    has_latin = tn.has_latin(text)
    if has_arabic and has_latin:
        return "mixed"
    if has_latin:
        return "en-US"
    return "ar-AE"


def is_near_duplicate(text_a: str, text_b: str) -> bool:
    """Exact-normalized and synonym-folded near-paraphrase detection."""
    if not text_a or not text_b:
        return False
    na = tn.normalize_arabic(text_a)
    nb = tn.normalize_arabic(text_b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if fuzz.token_sort_ratio(na, nb) >= NEAR_DUP_THRESHOLD:
        return True
    fa = emirati.emirati_fingerprint(text_a)
    fb = emirati.emirati_fingerprint(text_b)
    if fa and fb:
        if fa == fb:
            return True
        if fuzz.token_sort_ratio(fa, fb) >= NEAR_DUP_FINGERPRINT_THRESHOLD:
            return True
        # Template with one slot changed: high token-set overlap + similar length.
        if (
            fuzz.token_set_ratio(fa, fb) >= NEAR_DUP_TOKEN_SET_THRESHOLD
            and abs(len(fa.split()) - len(fb.split())) <= 2
            and fuzz.token_sort_ratio(fa, fb) >= 80
        ):
            return True
    return False


def validate_item(
    item: dict,
    existing_hashes: set[str],
    existing_texts: list[str],
    batch_hashes: set[str],
    *,
    speaker_gender: str | None = None,
    apply_safe_lexical_fixes: bool = True,
    batch_scenario_ids: set[str] | None = None,
    expected_scenario: str | None = None,
    expected_slot: dict | None = None,
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

    style = (item.get("style") or "neutral").strip().lower()
    domain = (item.get("domain") or "general").strip().lower()
    requested_dialect = (item.get("dialect") or "emirati").strip().lower()
    dialect = requested_dialect
    if language == "en-US":
        dialect = "english"
    elif language == "mixed":
        dialect = "mixed"

    # Emirati lexicon applies to ar-AE and to mixed utterances that were
    # authored as Emirati (requested dialect), even though stored dialect
    # becomes "mixed" for code-switched rows.
    apply_emirati_rules = emirati.is_emirati_arabic_item(
        "emirati" if requested_dialect == "emirati" else dialect,
        language,
    )

    # Post-generation Emirati lexical enforcement: safe fixes first, then
    # hard rejection of remaining dispreferred forms (no unsafe rewrites).
    if apply_emirati_rules and training:
        lexical = emirati.enforce_emirati_lexicon(
            display,
            training,
            dialect="emirati",
            language=language,
            apply_safe_fixes=apply_safe_lexical_fixes,
        )
        display = lexical["display_text"]
        training = lexical["training_text"]
        warnings.extend(lexical["warnings"])
        errors.extend(lexical["errors"])

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

        if apply_emirati_rules:
            gender = emirati.resolve_speaker_gender(
                {**item, "training_text": training, "display_text": display},
                default_gender=speaker_gender,
            )
            errors.extend(
                emirati.validate_gender_consistency(training, speaker_gender=gender)
            )

        h = tn.normalized_hash(training)
        if h in existing_hashes:
            errors.append("exact duplicate of an existing script")
        elif h in batch_hashes:
            errors.append("duplicate within this batch")
        else:
            for other in existing_texts:
                if is_near_duplicate(training, other):
                    errors.append("near-duplicate of an existing script")
                    break
        batch_hashes.add(h)
        existing_texts.append(training)

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

    tagged_scenario = scenario_planner.extract_scenario_id(item)
    if tagged_scenario:
        stag = f"scenario:{tagged_scenario}"
        if stag not in tags:
            tags = [*tags, stag]

    expected = (expected_scenario or "").strip() or None
    if expected_slot:
        expected = expected_slot.get("scenario") or expected

    if batch_scenario_ids is not None and tagged_scenario:
        scenario_ok = not expected or tagged_scenario == expected
        if scenario_ok:
            if tagged_scenario in batch_scenario_ids:
                errors.append(f"duplicate scenario '{tagged_scenario}' in this batch")
            else:
                batch_scenario_ids.add(tagged_scenario)

    if expected:
        if not tagged_scenario:
            errors.append(f"missing scenario tag; expected '{expected}'")
        elif tagged_scenario != expected:
            errors.append(
                f"scenario mismatch: expected '{expected}', got '{tagged_scenario}'"
            )
        expected_domain = (expected_slot or {}).get("domain")
        if expected_domain and domain != expected_domain.strip().lower():
            errors.append(
                f"domain mismatch: expected '{expected_domain}', got '{domain}'"
            )
        expected_style = (expected_slot or {}).get("style")
        if expected_style and style != expected_style.strip().lower():
            errors.append(
                f"style mismatch: expected '{expected_style}', got '{style}'"
            )
        expected_language = (expected_slot or {}).get("language")
        if expected_language and language != expected_language.strip():
            errors.append(
                f"language mismatch: expected '{expected_language}', got '{language}'"
            )
        expected_dialect = (expected_slot or {}).get("dialect")
        slot_dialect = (expected_dialect or "").strip().lower()
        item_dialect = requested_dialect if requested_dialect in DIALECTS else dialect
        if slot_dialect and item_dialect != slot_dialect:
            errors.append(
                f"dialect mismatch: expected '{slot_dialect}', got '{item_dialect}'"
            )

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


def validate_generation_batch(
    candidates: list[dict],
    *,
    expect_general_ratio: float | None = 0.25,
    scenario_plan: list[dict] | None = None,
) -> list[str]:
    """Batch-level diversity checks on validate_item computed payloads or raw items."""
    items = []
    for c in candidates:
        if "computed" in c:
            items.append(c["computed"])
        else:
            items.append(c)
    return scenario_planner.validate_batch_diversity(
        items,
        expect_general_ratio=expect_general_ratio,
        plan=scenario_plan,
    )

"""Deterministic scenario allocation for script generation batches.

Hierarchy enforced in code: Domain → Scenario → Intent → Utterance.

Each planned slot gets a distinct scenario when the pool allows it.
Domain spread alone is not treated as sufficient diversity.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass


DEFAULT_GENRES = [
    "transactional",
    "troubleshooting",
    "informational",
    "complaint",
    "advisory",
    "social",
]

# Core telecom / customer-care scenarios (domain tagged for validation).
TELECOM_SCENARIOS: list[dict[str, str]] = [
    {"scenario": "unexpected_invoice", "domain": "billing", "intent": "customer questions an unexpected invoice amount"},
    {"scenario": "vat_explanation", "domain": "billing", "intent": "agent explains VAT on the invoice"},
    {"scenario": "payment_failure", "domain": "billing", "intent": "customer payment failed in the app"},
    {"scenario": "duplicate_payment", "domain": "billing", "intent": "customer reports a duplicate charge"},
    {"scenario": "payment_confirmation", "domain": "billing", "intent": "agent confirms a successful payment"},
    {"scenario": "refund_request", "domain": "billing", "intent": "customer requests a refund for a wrong charge"},
    {"scenario": "billing_cycle", "domain": "billing", "intent": "customer asks when the billing cycle ends"},
    {"scenario": "change_payment_method", "domain": "customer_support", "intent": "customer wants to change payment method"},
    {"scenario": "data_package_exhausted", "domain": "telecom", "intent": "mobile data package finished early"},
    {"scenario": "roaming_activation", "domain": "telecom", "intent": "activate roaming before travel"},
    {"scenario": "weak_signal", "domain": "technical_support", "intent": "weak mobile signal at home"},
    {"scenario": "slow_internet", "domain": "technical_support", "intent": "slow mobile or home internet"},
    {"scenario": "elife_outage", "domain": "technical_support", "intent": "eLife / fiber service interrupted"},
    {"scenario": "router_troubleshoot", "domain": "technical_support", "intent": "agent guides router reboot"},
    {"scenario": "wifi_issue", "domain": "technical_support", "intent": "WiFi drops while 5G works"},
    {"scenario": "installation_appointment", "domain": "customer_support", "intent": "reschedule fiber installation"},
    {"scenario": "delivery_appointment", "domain": "customer_support", "intent": "SIM / device delivery timing"},
    {"scenario": "esim_transfer", "domain": "telecom", "intent": "move number to eSIM"},
    {"scenario": "sim_activation", "domain": "telecom", "intent": "new SIM activated but SMS fails"},
    {"scenario": "package_cancellation", "domain": "sales", "intent": "cancel an add-on after this cycle"},
    {"scenario": "plan_upgrade", "domain": "sales", "intent": "upgrade to a higher plan or offer"},
    {"scenario": "plan_downgrade", "domain": "sales", "intent": "downgrade because usage is low"},
    {"scenario": "renewal_offer", "domain": "sales", "intent": "renewal or promotional offer"},
    {"scenario": "otp_verification", "domain": "customer_support", "intent": "OTP / identity verification in the app"},
    {"scenario": "recharge_balance", "domain": "telecom", "intent": "recharge prepaid balance"},
    {"scenario": "app_support", "domain": "customer_support", "intent": "e& UAE App will not open"},
    {"scenario": "coverage_5g", "domain": "telecom", "intent": "5G coverage question"},
    {"scenario": "complaint_followup", "domain": "customer_support", "intent": "repeat complaint and ticket number"},
    {"scenario": "account_update", "domain": "customer_support", "intent": "update account holder information"},
    {"scenario": "service_request", "domain": "customer_support", "intent": "open a service request"},
    {"scenario": "voice_call_quality", "domain": "technical_support", "intent": "calls drop or sound poor"},
    {"scenario": "sms_not_sending", "domain": "technical_support", "intent": "SMS not sending"},
]

HR_SCENARIOS: list[dict[str, str]] = [
    {"scenario": "hr_leave_balance", "domain": "hr", "intent": "employee checks remaining annual leave balance"},
    {"scenario": "hr_annual_leave", "domain": "hr", "intent": "employee requests annual leave dates"},
    {"scenario": "hr_sick_leave", "domain": "hr", "intent": "employee reports sick leave for today"},
    {"scenario": "hr_payroll", "domain": "hr", "intent": "employee asks about a payroll discrepancy"},
    {"scenario": "hr_salary_clarification", "domain": "hr", "intent": "employee clarifies a salary component or deduction"},
    {"scenario": "hr_employment_letter", "domain": "hr", "intent": "request an employment letter for embassy or bank"},
    {"scenario": "hr_update_info", "domain": "hr", "intent": "update employee contact or personal information"},
    {"scenario": "hr_attendance", "domain": "hr", "intent": "attendance issue or missing punch correction"},
    {"scenario": "hr_training", "domain": "hr", "intent": "register for a workplace training course"},
    {"scenario": "hr_benefits", "domain": "hr", "intent": "inquiry about employee benefits or insurance"},
    {"scenario": "hr_wfh", "domain": "hr", "intent": "request work-from-home for a specific day"},
    {"scenario": "hr_onboarding", "domain": "hr", "intent": "new employee onboarding or joining a team"},
    {"scenario": "hr_manager_message", "domain": "hr", "intent": "employee message to manager about schedule or task"},
    {"scenario": "hr_overtime", "domain": "hr", "intent": "question about overtime approval or compensation"},
]

GENERAL_SCENARIOS: list[dict[str, str]] = [
    {"scenario": "friends_evening", "domain": "general", "intent": "friends planning after Maghrib"},
    {"scenario": "family_dinner", "domain": "general", "intent": "family conversation about dinner"},
    {"scenario": "restaurant_booking", "domain": "general", "intent": "restaurant is busy, change booking time"},
    {"scenario": "shopping", "domain": "general", "intent": "shopping and not finding the right size"},
    {"scenario": "directions", "domain": "general", "intent": "asking for directions or parking"},
    {"scenario": "colleagues_coffee", "domain": "general", "intent": "colleagues chatting after a meeting"},
    {"scenario": "traffic", "domain": "general", "intent": "traffic on a main road"},
    {"scenario": "travel_return", "domain": "general", "intent": "just returned from travel"},
    {"scenario": "appointment_confirm", "domain": "general", "intent": "confirm a non-telecom appointment"},
    {"scenario": "weekend_plans", "domain": "general", "intent": "weekend plans with friends"},
    {"scenario": "weather", "domain": "general", "intent": "hot weather / outdoor plans"},
    {"scenario": "daily_errand", "domain": "general", "intent": "running a daily errand"},
    {"scenario": "public_transport", "domain": "general", "intent": "metro or bus delay / platform question"},
    {"scenario": "taxi_ride", "domain": "general", "intent": "taxi or ride-hailing pickup coordination"},
    {"scenario": "grocery_run", "domain": "general", "intent": "quick grocery shopping conversation"},
    {"scenario": "school_pickup", "domain": "general", "intent": "family coordinating school pickup"},
    {"scenario": "neighbor_chat", "domain": "general", "intent": "casual chat with a neighbor"},
    {"scenario": "sports_plans", "domain": "general", "intent": "making plans to play or watch sports"},
]

TELECOM_BUCKET_DOMAINS = {
    "customer_support",
    "telecom",
    "billing",
    "technical_support",
    "sales",
    "hr",
    "numbers_dates",
    "other",
}


@dataclass(frozen=True)
class ScenarioSlot:
    index: int
    bucket: str  # telecom | general
    domain: str
    scenario: str
    intent: str
    speaker_role: str  # customer | agent | employee
    speaker_gender: str  # any | male | female
    language: str  # ar-AE | en-US | mixed
    dialect: str  # emirati | msa | english | mixed
    style: str
    genre: str

    def to_dict(self) -> dict:
        return asdict(self)


def _infer_speaker_role(intent: str, domain: str) -> str:
    """Derive conversational role from intent text and domain."""
    low = intent.lower()
    if domain == "hr":
        return "employee"
    if "agent" in low or "advisor" in low:
        return "agent"
    if "employee" in low:
        return "employee"
    return "customer"


def _slot_dialect(language: str, batch_dialect: str) -> str:
    lang = (language or "ar-AE").strip()
    if lang == "en-US":
        return "english"
    if lang == "mixed":
        return "mixed"
    return (batch_dialect or "emirati").strip().lower()


def slot_from_dict(data: dict) -> ScenarioSlot:
    """Rehydrate a plan slot from a dict (API / params payload)."""
    return ScenarioSlot(
        index=int(data.get("index", 0)),
        bucket=str(data.get("bucket", "telecom")),
        domain=str(data.get("domain", "general")),
        scenario=str(data.get("scenario", "unknown")),
        intent=str(data.get("intent", "")),
        speaker_role=str(data.get("speaker_role", "customer")),
        speaker_gender=str(data.get("speaker_gender", "any")),
        language=str(data.get("language", "ar-AE")),
        dialect=str(data.get("dialect", "emirati")),
        style=str(data.get("style", "neutral")),
        genre=str(data.get("genre", "transactional")),
    )


def extract_scenario_id(item: dict) -> str | None:
    """Read scenario id from item field or scenario:* tag."""
    raw = (item.get("scenario") or "").strip()
    if raw:
        return raw
    for tag in item.get("tags") or []:
        text = str(tag)
        if text.startswith("scenario:"):
            return text.split(":", 1)[1]
    return None


def telecom_general_counts(count: int) -> tuple[int, int]:
    """Exact 75/25 split that always sums to count."""
    count = max(0, int(count))
    telecom = round(count * 0.75)
    if count >= 4 and telecom == count:
        telecom = count - 1
    if count >= 4 and telecom == 0:
        telecom = 1
    general = count - telecom
    return telecom, general


def hr_slot_count(telecom_n: int) -> int:
    if telecom_n < 4:
        return 0
    return max(1, min(4, round(telecom_n * 0.10)))


def _filter_telecom_scenarios(allowed_domains: list[str] | None) -> list[dict[str, str]]:
    if not allowed_domains:
        return list(TELECOM_SCENARIOS)
    allowed = {d.strip().lower() for d in allowed_domains if d.strip().lower() not in ("general", "hr")}
    if not allowed:
        allowed = {d for d in TELECOM_BUCKET_DOMAINS if d not in ("general", "hr")}
    filtered = [s for s in TELECOM_SCENARIOS if s["domain"] in allowed]
    return filtered or list(TELECOM_SCENARIOS)


def _include_hr(allowed_domains: list[str] | None) -> bool:
    return True


def _domain_order(pool: list[dict[str, str]], preferred_domains: list[str] | None) -> list[str]:
    by_domain = {s["domain"] for s in pool}
    order: list[str] = []
    if preferred_domains:
        for d in preferred_domains:
            dl = d.strip().lower()
            if dl in by_domain and dl not in order:
                order.append(dl)
    for d in sorted(by_domain):
        if d not in order:
            order.append(d)
    return order


def _allocate_unique_scenarios(
    pool: list[dict[str, str]],
    count: int,
    *,
    preferred_domains: list[str] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, str]]:
    """Pick `count` scenarios: unique first, round-robin across domains.

    Reuses a scenario only after every scenario in the pool has been used once,
    and never places the same scenario in consecutive slots when avoidable.
    """
    if count <= 0 or not pool:
        return []

    by_domain: dict[str, list[dict[str, str]]] = defaultdict(list)
    for entry in pool:
        by_domain[entry["domain"]].append(entry)

    domain_order = _domain_order(pool, preferred_domains)
    if rng is not None:
        rng.shuffle(domain_order)
        for entries in by_domain.values():
            rng.shuffle(entries)
    max_depth = max(len(by_domain[d]) for d in domain_order)

    # Round 0..max_depth: one scenario per domain per round → max diversity.
    rounds: list[dict[str, str]] = []
    for depth in range(max_depth):
        for domain in domain_order:
            items = by_domain[domain]
            if depth < len(items):
                rounds.append(items[depth])

    if not rounds:
        return []

    result: list[dict[str, str]] = []
    if count <= len(rounds):
        return rounds[:count]

    result.extend(rounds)
    idx = 0
    while len(result) < count:
        cand = rounds[idx % len(rounds)]
        if result and cand["scenario"] == result[-1]["scenario"]:
            idx += 1
            if idx > len(rounds) * 2:
                break
            continue
        result.append(cand)
        idx += 1
    return result[:count]


def _spread_indices(total: int, count: int) -> list[int]:
    if count <= 0 or total <= 0:
        return []
    if count >= total:
        return list(range(total))
    step = total / count
    return [min(total - 1, int(round(i * step + step / 2 - 0.5))) for i in range(count)]


def _slot_from_entry(
    entry: dict[str, str],
    *,
    bucket: str,
    language: str,
    dialect: str,
    style: str,
    genre: str,
    speaker_gender: str,
) -> ScenarioSlot:
    domain = entry["domain"]
    intent = entry["intent"]
    return ScenarioSlot(
        index=-1,
        bucket=bucket,
        domain=domain,
        scenario=entry["scenario"],
        intent=intent,
        speaker_role=_infer_speaker_role(intent, domain),
        speaker_gender=speaker_gender,
        language=language,
        dialect=dialect,
        style=style,
        genre=genre,
    )


def plan_generation_batch(
    count: int,
    *,
    domains: list[str] | None = None,
    include_general: bool = True,
    include_hr: bool | None = None,
    languages: list[str] | None = None,
    dialect: str = "emirati",
    styles: list[str] | None = None,
    genres: list[str] | None = None,
    speaker_gender: str = "any",
    variation_seed: int | None = None,
) -> list[ScenarioSlot]:
    """Build a varied batch plan with a 75/25 business/general split.

    ``variation_seed`` changes scenario and genre ordering while preserving the
    requested distribution. Supplying the same seed reproduces the same plan.
    """
    count = max(0, int(count))
    if count == 0:
        return []

    if include_general:
        telecom_n, general_n = telecom_general_counts(count)
    else:
        telecom_n, general_n = count, 0

    hr_enabled = _include_hr(domains) if include_hr is None else include_hr
    hr_n = hr_slot_count(telecom_n) if hr_enabled else 0
    core_n = max(0, telecom_n - hr_n)

    domain_rotation = [
        d for d in (domains or [])
        if d and d not in ("general",)
    ] or ["customer_support", "telecom", "billing", "technical_support", "sales", "hr"]

    lang_list = [l for l in (languages or ["ar-AE"]) if l] or ["ar-AE"]
    style_list = [s for s in (styles or ["neutral"]) if s] or ["neutral"]
    genre_list = [g for g in (genres or DEFAULT_GENRES) if g] or list(DEFAULT_GENRES)
    rng = random.Random(variation_seed) if variation_seed is not None else None
    if rng is not None:
        rng.shuffle(genre_list)
    batch_dialect = (dialect or "emirati").strip().lower()
    batch_gender = (speaker_gender or "any").strip().lower()

    def _slot_meta(slot_index: int) -> tuple[str, str, str, str]:
        language = lang_list[slot_index % len(lang_list)]
        style = style_list[slot_index % len(style_list)]
        genre = genre_list[slot_index % len(genre_list)]
        return language, _slot_dialect(language, batch_dialect), style, genre

    telecom_pool = _filter_telecom_scenarios(domains)
    core_entries = _allocate_unique_scenarios(
        telecom_pool,
        core_n,
        preferred_domains=[d for d in domain_rotation if d != "hr"],
        rng=rng,
    )
    hr_entries = _allocate_unique_scenarios(
        HR_SCENARIOS, hr_n, preferred_domains=["hr"], rng=rng
    )
    general_entries = _allocate_unique_scenarios(
        GENERAL_SCENARIOS,
        general_n,
        preferred_domains=["general"],
        rng=rng,
    )

    core_slots: list[ScenarioSlot] = []
    for i, e in enumerate(core_entries):
        lang, dia, sty, genre = _slot_meta(len(core_slots))
        core_slots.append(
            _slot_from_entry(
                e,
                bucket="telecom",
                language=lang,
                dialect=dia,
                style=sty,
                genre=genre,
                speaker_gender=batch_gender,
            )
        )
    hr_slots: list[ScenarioSlot] = []
    for e in hr_entries:
        lang, dia, sty, genre = _slot_meta(len(core_slots) + len(hr_slots))
        hr_slots.append(
            _slot_from_entry(
                e,
                bucket="telecom",
                language=lang,
                dialect=dia,
                style=sty,
                genre=genre,
                speaker_gender=batch_gender,
            )
        )

    telecom_merged: list[ScenarioSlot] = list(core_slots)
    for pos, hr_slot in zip(_spread_indices(len(telecom_merged) + len(hr_slots), hr_n), hr_slots):
        telecom_merged.insert(min(pos, len(telecom_merged)), hr_slot)

    general_slots: list[ScenarioSlot] = []
    base_idx = len(telecom_merged)
    for i, e in enumerate(general_entries):
        lang, dia, sty, genre = _slot_meta(base_idx + i)
        general_slots.append(
            _slot_from_entry(
                e,
                bucket="general",
                language=lang,
                dialect=dia,
                style=sty,
                genre=genre,
                speaker_gender=batch_gender,
            )
        )

    ordered: list[ScenarioSlot] = []
    t_i = g_i = 0
    while t_i < len(telecom_merged) or g_i < len(general_slots):
        for _ in range(3):
            if t_i < len(telecom_merged):
                ordered.append(telecom_merged[t_i])
                t_i += 1
        if g_i < len(general_slots):
            ordered.append(general_slots[g_i])
            g_i += 1

    final = ordered[:count]
    return [
        ScenarioSlot(
            index=i,
            bucket=slot.bucket,
            domain=slot.domain,
            scenario=slot.scenario,
            intent=slot.intent,
            speaker_role=slot.speaker_role,
            speaker_gender=slot.speaker_gender,
            language=slot.language,
            dialect=slot.dialect,
            style=slot.style,
            genre=slot.genre,
        )
        for i, slot in enumerate(final)
    ]


def slice_plan(plan: list[dict], offset: int, count: int) -> list[dict]:
    """Return a contiguous slice of a full scenario plan for mini-batches."""
    return list(plan[offset : offset + count])


def plan_as_dicts(plan: list[ScenarioSlot]) -> list[dict]:
    return [s.to_dict() for s in plan]


def summarize_plan(plan: list[ScenarioSlot]) -> dict:
    telecom = sum(1 for s in plan if s.bucket == "telecom")
    general = sum(1 for s in plan if s.bucket == "general")
    hr = sum(1 for s in plan if s.domain == "hr")
    scenarios = {s.scenario for s in plan}
    domains = {s.domain for s in plan}
    per_domain = Counter(s.domain for s in plan)
    per_domain_scenarios = {
        domain: len({s.scenario for s in plan if s.domain == domain})
        for domain in domains
    }
    duplicate_scenarios = len(plan) - len(scenarios)
    return {
        "total": len(plan),
        "telecom": telecom,
        "general": general,
        "hr": hr,
        "unique_scenarios": len(scenarios),
        "duplicate_scenarios_in_plan": duplicate_scenarios,
        "unique_domains": len(domains),
        "per_domain_counts": dict(per_domain),
        "per_domain_unique_scenarios": per_domain_scenarios,
        "telecom_ratio": (telecom / len(plan)) if plan else 0.0,
        "general_ratio": (general / len(plan)) if plan else 0.0,
        "hr_ratio": (hr / len(plan)) if plan else 0.0,
    }


def validate_plan(plan: list[ScenarioSlot]) -> list[str]:
    """Validate the deterministic plan itself meets diversity rules."""
    issues: list[str] = []
    if not plan:
        return ["empty plan"]

    scenarios = [s.scenario for s in plan]
    if len(scenarios) != len(set(scenarios)):
        dupes = [s for s, c in Counter(scenarios).items() if c > 1]
        issues.append(f"plan repeats scenarios: {', '.join(dupes[:5])}")

    for i in range(1, len(plan)):
        if plan[i].scenario == plan[i - 1].scenario:
            issues.append(
                f"consecutive plan slots share scenario '{plan[i].scenario}'"
            )
            break

    total = len(plan)
    if total >= 20:
        per_domain = Counter(s.domain for s in plan if s.domain != "general")
        for domain, n in per_domain.items():
            unique = len({s.scenario for s in plan if s.domain == domain})
            if n >= 2 and unique < 2:
                issues.append(
                    f"domain '{domain}' has {n} slots but only {unique} distinct scenario"
                )

    return issues


def validate_batch_diversity(
    items: list[dict],
    *,
    min_unique_scenarios: int | None = None,
    expect_general_ratio: float | None = 0.25,
    ratio_tolerance: float = 0.15,
    min_hr_items: int = 1,
    plan: list[dict] | None = None,
) -> list[str]:
    """Return issues about batch-level scenario / domain concentration."""
    issues: list[str] = []
    if not items:
        return ["empty batch"]

    domains = [(it.get("domain") or "general").strip().lower() for it in items]
    general_n = sum(1 for d in domains if d == "general")
    hr_n = sum(1 for d in domains if d == "hr")
    total = len(items)
    general_ratio = general_n / total

    if expect_general_ratio is not None and total >= 4:
        if abs(general_ratio - expect_general_ratio) > ratio_tolerance:
            issues.append(
                f"general domain ratio {general_ratio:.2f} outside "
                f"target {expect_general_ratio:.2f}±{ratio_tolerance:.2f}"
            )

    if total >= 8 and hr_n < min_hr_items:
        issues.append(
            f"batch of {total} has {hr_n} hr-domain items (expected ≥ {min_hr_items})"
        )

    scenarios: list[str] = []
    for it in items:
        sid = extract_scenario_id(it)
        scenarios.append(sid or (it.get("domain") or "unknown"))

    unique = len(set(scenarios))
    if min_unique_scenarios is None:
        min_unique_scenarios = max(3, min(total, total // 2))
    if total >= 6 and unique < min_unique_scenarios:
        issues.append(
            f"only {unique} distinct scenarios in a batch of {total} "
            f"(need ≥ {min_unique_scenarios})"
        )

    dupe_ids = [s for s, c in Counter(scenarios).items() if c > 1 and not s.startswith("unknown")]
    if dupe_ids:
        issues.append(
            f"duplicate scenario ids in batch: {', '.join(dupe_ids[:5])}"
        )

    if total >= 20:
        per_domain = Counter(d for d in domains if d != "general")
        for domain, n in per_domain.items():
            domain_scenarios = {
                scenarios[i]
                for i, d in enumerate(domains)
                if d == domain and not scenarios[i].startswith("unknown")
            }
            if n >= 2 and len(domain_scenarios) < 2:
                issues.append(
                    f"domain '{domain}' has {n} items but only one distinct scenario"
                )

    streak = 1
    for i in range(1, len(scenarios)):
        if scenarios[i] == scenarios[i - 1]:
            streak += 1
            if streak > 1:
                issues.append(
                    f"consecutive items share scenario '{scenarios[i]}'"
                )
                break
        else:
            streak = 1

    if plan:
        planned = [p.get("scenario") for p in plan if p.get("scenario")]
        if len(planned) == total:
            missing = [s for s in planned if s not in scenarios]
            if missing:
                issues.append(
                    f"generated batch missing planned scenarios: {', '.join(missing[:5])}"
                )

    return issues

"""Tests for Emirati dialect governance, scenario planning, and near-dup logic.

These tests mock the LLM and exercise deterministic planner/validator code only.
"""
from __future__ import annotations

import json

import pytest

from app.services import emirati_dialect as emirati
from app.services import llm_scripts
from app.services import scenario_planner


# ---------------------------------------------------------------------------
# A. Emirati vocabulary detection / safe fixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad,preferred_substr",
    [
        ("أبا أرد للباقة السابق", "اللي طاف"),
        ("أبغا أشيك على الرصيد", "ابا"),
        ("رجعت من الفرع الحين", "ردت"),
        ("الانترنت عندي بطيء", "نت"),
        ("أروح عن قريب", "عقب شوي"),
        ("الباقة الماضية أغلى", "اللي طاف"),
        ("ليش ما طفيت اللمبة", "ليت"),
        ("ليش ما تطفي الراوتر", "تبند"),
        ("من غير رسوم إضافية", "من دون"),
        ("أبي أغير الباقة", "تبدل"),
        ("وصلت أبكر من الموعد", "من وقت"),
        ("وصلت بدري اليوم", "من وقت"),
        ("هلا بك في خدمة العملاء", "مرحبا"),
        ("المشكلة ظلت من أمس", "تمت"),
        ("عشان جي ما قدرت أحضر", "عسب جي"),
    ],
)
def test_dispreferred_emirati_forms_are_detected(bad, preferred_substr):
    issues = emirati.find_dispreferred_forms(bad)
    assert issues, f"expected issues in: {bad}"
    assert any(preferred_substr in i.preferred for i in issues)


@pytest.mark.parametrize(
    "good",
    [
        "أبا أرد للباقة اللي طافت",
        "النت عندي بطيء",
        "أروح عقب شوي",
        "ليش ما بندت الليت",
        "من دون رسوم إضافية",
        "أبي أبدل الباقة",
        "وصلت من وقت",
        "مرحبا في خدمة العملاء",
        "المشكلة تمت من أمس",
        "عسب جي ما قدرت أحضر",
        "بنظهر قبل المغرب",
        "بنطلع عقب المغرب",
    ],
)
def test_preferred_emirati_forms_pass(good):
    assert emirati.find_dispreferred_forms(good) == []


def test_safe_fixes_rewrite_unambiguous_forms():
    text, applied = emirati.apply_safe_emirati_fixes(
        "أبغا أشيك على الانترنت عن قريب من غير رسوم"
    )
    assert "أبغا" not in text and "ابغا" not in text
    assert "ابا" in text
    assert "نت" in text
    assert "عقب شوي" in text
    assert "من دون" in text
    assert applied


def test_unsafe_forms_are_not_silently_rewritten():
    # رجعت / تطفي / لمبة / تغير / ظلت stay for rejection rather than rewrite.
    original = "رجعت البيت وطلبت تطفي اللمبة وتغير الباقة وظلت المشكلة"
    text, applied = emirati.apply_safe_emirati_fixes(original)
    assert text == original
    assert applied == []
    assert emirati.validate_emirati_lexicon(original)


def test_temporal_previous_is_safely_rewritten_with_gender():
    masc, applied_m = emirati.apply_safe_emirati_fixes("الشهر السابق أغلى")
    assert masc == "الشهر اللي طاف أغلى"
    assert "al_madi_temporal" in applied_m

    fem, applied_f = emirati.apply_safe_emirati_fixes("الباقة السابقة أغلى")
    assert fem == "الباقة اللي طافت أغلى"
    assert "al_madi_temporal" in applied_f
    assert emirati.find_dispreferred_forms(fem) == []


def test_enforce_emirati_lexicon_post_generation():
    result = emirati.enforce_emirati_lexicon(
        "أبغا أشيك على الانترنت",
        "أبغا أشيك على الانترنت",
        dialect="emirati",
        language="ar-AE",
    )
    assert result["applied"] is True
    assert "ابا" in result["training_text"]
    assert "نت" in result["training_text"]
    assert not result["errors"]

    rejected = emirati.enforce_emirati_lexicon(
        "رجعت من الفرع",
        "رجعت من الفرع",
        dialect="emirati",
        language="ar-AE",
    )
    assert rejected["errors"]
    assert any("Emirati lexical consistency" in e for e in rejected["errors"])
    assert any("ردت" in e for e in rejected["errors"])

    skipped = emirati.enforce_emirati_lexicon(
        "أريد الباقة السابقة",
        "أريد الباقة السابقة",
        dialect="msa",
        language="ar-AE",
    )
    assert skipped["applied"] is False
    assert skipped["errors"] == []


def test_preferred_forms_prompt_block_lists_mappings():
    block = emirati.preferred_forms_prompt_block()
    assert "السابق → اللي طاف" in block
    assert "أبغا → ابا" in block
    assert "عشان جي → عسب جي" in block


def test_fi_al_madi_idiom_is_not_flagged():
    assert emirati.find_dispreferred_forms("في الماضي كانت التغطية أحسن") == []


def test_emirati_rules_skip_english_and_msa():
    english = "I want to check my previous internet package"
    msa = "أريد أن أتحقق من الباقة السابقة على الإنترنت"

    assert emirati.is_emirati_arabic_item("english", "en-US") is False
    assert emirati.is_emirati_arabic_item("msa", "ar-AE") is False

    # Validator path: English / MSA items must not gain Emirati lexicon errors.
    en = llm_scripts.validate_item(
        {
            "display_text": english,
            "training_text": english,
            "language": "en-US",
            "dialect": "english",
        },
        set(),
        [],
        set(),
    )
    assert en["ok"] is True
    assert not any("Emirati lexical" in e or "non-Emirati" in e for e in en["errors"])

    msa_item = llm_scripts.validate_item(
        {
            "display_text": msa,
            "training_text": msa,
            "language": "ar-AE",
            "dialect": "msa",
        },
        set(),
        [],
        set(),
        apply_safe_lexical_fixes=False,
    )
    assert not any("Emirati lexical" in e or "non-Emirati" in e for e in msa_item["errors"])


def test_brand_and_unrelated_words_not_corrupted():
    text = "مرحبا، باقة Freedom Life ما تتبدل من دون سبب"
    assert emirati.find_dispreferred_forms(text) == []
    fixed, applied = emirati.apply_safe_emirati_fixes(text)
    assert fixed == text
    assert applied == []


def test_validate_item_applies_safe_fix_and_rejects_remaining():
    ok_item = llm_scripts.validate_item(
        {
            "display_text": "أبغا أشيك على النت",
            "training_text": "أبغا أشيك على النت",
            "language": "ar-AE",
            "dialect": "emirati",
            "domain": "telecom",
        },
        set(),
        [],
        set(),
    )
    assert ok_item["ok"] is True
    assert "ابا" in ok_item["computed"]["training_text"]
    assert "أبغا" not in ok_item["computed"]["training_text"]

    bad_item = llm_scripts.validate_item(
        {
            "display_text": "رجعت من الفرع الحين",
            "training_text": "رجعت من الفرع الحين",
            "language": "ar-AE",
            "dialect": "emirati",
        },
        set(),
        [],
        set(),
    )
    assert bad_item["ok"] is False
    assert any("ردت" in e for e in bad_item["errors"])


# ---------------------------------------------------------------------------
# B. Gender consistency (any | male | female) — MANDATORY
# ---------------------------------------------------------------------------

def test_male_context_rejects_rabeeati():
    errors = emirati.validate_gender_consistency(
        "أنا كنت ويا ربيعاتي في المول",
        speaker_gender="male",
    )
    assert errors
    assert any("ربعي" in e for e in errors)


def test_female_context_keeps_rabeeati():
    errors = emirati.validate_gender_consistency(
        "أنا كنت ويا ربيعاتي في المول",
        speaker_gender="female",
    )
    assert errors == []


def test_any_does_not_reject_rabeeati_alone():
    assert (
        emirati.validate_gender_consistency(
            "بروح ويا ربيعاتي",
            speaker_gender="any",
        )
        == []
    )


def test_male_preferred_form_passes():
    assert (
        emirati.validate_gender_consistency(
            "أنا كنت ويا ربعي في المول",
            speaker_gender="male",
        )
        == []
    )


def test_female_rejects_masculine_self_reference():
    errors = emirati.validate_gender_consistency(
        "أنا رجل وكنت ويا ربعي",
        speaker_gender="female",
    )
    assert errors
    assert any("female" in e.lower() or "masculine" in e.lower() for e in errors)


def test_male_rejects_feminine_self_reference():
    errors = emirati.validate_gender_consistency(
        "أنا موظفة وأبا أكلم خدمة العملاء",
        speaker_gender="male",
    )
    assert errors
    assert any("male" in e.lower() for e in errors)


def test_batch_male_gender_not_overridden_by_item_tags():
    """Batch speaker_gender=male must lock every item — no mid-batch switch."""
    resolved = emirati.resolve_speaker_gender(
        {
            "display_text": "بروح ويا ربيعاتي",
            "tags": ["female", "gender:feminine"],
            "speaker_gender": "female",
        },
        default_gender="male",
    )
    assert resolved == "male"


def test_batch_female_gender_not_overridden_by_masculine_cues():
    resolved = emirati.resolve_speaker_gender(
        {"display_text": "أنا رجل ويا ربعي", "tags": ["male"]},
        default_gender="female",
    )
    assert resolved == "female"


def test_validate_item_gender_via_param_and_tags():
    bad = llm_scripts.validate_item(
        {
            "display_text": "بروح ويا ربيعاتي",
            "language": "ar-AE",
            "dialect": "emirati",
            "tags": ["male"],
        },
        set(),
        [],
        set(),
        speaker_gender="male",
    )
    assert bad["ok"] is False
    assert any("male" in e.lower() or "ربعي" in e for e in bad["errors"])

    good = llm_scripts.validate_item(
        {
            "display_text": "بروح ويا ربيعاتي",
            "language": "ar-AE",
            "dialect": "emirati",
        },
        set(),
        [],
        set(),
        speaker_gender="female",
    )
    assert good["ok"] is True


def test_speaker_gender_prompt_block_is_mandatory():
    male = emirati.speaker_gender_prompt_block("male")
    assert "MANDATORY" in male
    assert "ربعي" in male
    assert "ربيعاتي" in male
    female = emirati.speaker_gender_prompt_block("female")
    assert "MANDATORY" in female
    assert "feminine" in female.lower() or "ربيعاتي" in female


def test_normalize_speaker_gender_aliases():
    assert emirati.normalize_speaker_gender(None) == "any"
    assert emirati.normalize_speaker_gender("unspecified") == "any"
    assert emirati.normalize_speaker_gender("masculine") == "male"
    assert emirati.normalize_speaker_gender("feminine") == "female"
    assert emirati.normalize_speaker_gender("male") == "male"


# ---------------------------------------------------------------------------
# C. Scenario allocation (no LLM)
# ---------------------------------------------------------------------------

def test_plan_uses_unique_scenarios_for_batch_20():
    plan = scenario_planner.plan_generation_batch(20)
    scenarios = [s.scenario for s in plan]
    assert len(scenarios) == len(set(scenarios))
    assert scenario_planner.validate_plan(plan) == []


def test_plan_multiple_scenarios_per_domain_for_large_batch():
    plan = scenario_planner.plan_generation_batch(30)
    summary = scenario_planner.summarize_plan(plan)
    for domain, unique in summary["per_domain_unique_scenarios"].items():
        count = summary["per_domain_counts"].get(domain, 0)
        if domain != "general" and count >= 2:
            assert unique >= 2, f"domain {domain} should have ≥2 scenarios"


def test_plan_distributes_75_25_for_20_items():
    plan = scenario_planner.plan_generation_batch(
        20,
        domains=["customer_support", "telecom", "billing", "technical_support", "sales", "hr"],
    )
    summary = scenario_planner.summarize_plan(plan)
    assert summary["total"] == 20
    assert summary["telecom"] == 15
    assert summary["general"] == 5
    assert summary["hr"] >= 1
    assert summary["unique_scenarios"] >= 10
    assert summary["unique_domains"] >= 4
    assert all(s.domain == "general" for s in plan if s.bucket == "general")
    assert all(s.domain != "general" for s in plan if s.bucket == "telecom")


def test_plan_guarantees_hr_slots_for_typical_batches():
    for count in (10, 20, 30, 50):
        plan = scenario_planner.plan_generation_batch(count)
        hr_items = [s for s in plan if s.domain == "hr"]
        assert len(hr_items) >= 1, f"expected HR in batch of {count}"
        assert all(s.scenario.startswith("hr_") for s in hr_items)
        assert len({s.scenario for s in hr_items}) >= 1


def test_hr_scenarios_use_hr_domain_not_other():
    assert all(s["domain"] == "hr" for s in scenario_planner.HR_SCENARIOS)
    assert len(scenario_planner.HR_SCENARIOS) >= 10


def test_build_user_prompt_mentions_hr_when_planned():
    from app.config import Settings

    params = {
        "count": 20,
        "domains": ["billing", "telecom", "hr"],
        "styles": ["neutral"],
        "languages": ["ar-AE"],
        "dialect": "emirati",
    }
    prompt = llm_scripts.build_user_prompt(params, Settings())
    assert 'domain="hr"' in prompt or "HR/workplace" in prompt
    assert any("hr_" in line for line in prompt.splitlines())


def test_plan_avoids_long_identical_scenario_streaks():
    plan = scenario_planner.plan_generation_batch(40)
    scenarios = [s.scenario for s in plan]
    streak = 1
    max_streak = 1
    for i in range(1, len(scenarios)):
        if scenarios[i] == scenarios[i - 1]:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1
    assert max_streak <= 2


def test_ensure_scenario_plan_attached_to_params():
    params = {
        "count": 12,
        "domains": ["billing", "technical_support", "sales"],
    }
    plan = llm_scripts.ensure_scenario_plan(params)
    assert len(plan) == 12
    assert params["scenario_plan"] is plan
    # Second call reuses the same plan.
    assert llm_scripts.ensure_scenario_plan(params) is plan


def test_build_user_prompt_includes_emirati_lexical_block():
    from app.config import Settings

    prompt = llm_scripts.build_user_prompt(
        {
            "count": 4,
            "domains": ["billing"],
            "styles": ["neutral"],
            "languages": ["ar-AE"],
            "dialect": "emirati",
        },
        Settings(),
    )
    assert "Emirati lexical consistency" in prompt
    assert "السابق → اللي طاف" in prompt
    assert "أبغا → ابا" in prompt


def test_system_prompt_documents_emirati_lexical_consistency():
    assert "Emirati lexical consistency" in llm_scripts.SYSTEM_PROMPT
    assert "السابق → اللي طاف" in llm_scripts.SYSTEM_PROMPT
    assert "عشان جي → عسب جي" in llm_scripts.SYSTEM_PROMPT


def test_plan_slot_has_all_required_fields():
    plan = scenario_planner.plan_generation_batch(
        10,
        languages=["ar-AE"],
        dialect="emirati",
        styles=["neutral", "formal"],
        speaker_gender="male",
    )
    required = {
        "domain",
        "scenario",
        "intent",
        "speaker_role",
        "speaker_gender",
        "language",
        "dialect",
        "style",
    }
    for slot in plan:
        data = slot.to_dict()
        assert required.issubset(data.keys())
        assert data["speaker_gender"] == "male"
        assert data["language"] == "ar-AE"
        assert data["dialect"] == "emirati"
        assert data["speaker_role"] in ("customer", "agent", "employee")


def test_slice_plan_preserves_global_order():
    full = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(12))
    scenarios = [s["scenario"] for s in full]
    batch1 = scenario_planner.slice_plan(full, 0, 5)
    batch2 = scenario_planner.slice_plan(full, 5, 5)
    batch3 = scenario_planner.slice_plan(full, 10, 2)
    assert [s["scenario"] for s in batch1] == scenarios[:5]
    assert [s["scenario"] for s in batch2] == scenarios[5:10]
    assert [s["scenario"] for s in batch3] == scenarios[10:12]


def test_build_user_prompt_includes_scenario_plan_lines():
    from app.config import Settings

    params = {
        "count": 8,
        "domains": ["billing", "telecom"],
        "styles": ["neutral"],
        "languages": ["ar-AE"],
        "dialect": "emirati",
        "speaker_gender": "male",
    }
    prompt = llm_scripts.build_user_prompt(params, Settings())
    assert "MANDATORY SCENARIO ASSIGNMENTS" in prompt
    assert "ITEM 1" in prompt
    assert "Scenario:" in prompt
    assert "Intent:" in prompt
    assert "Batch speaker gender: male" in prompt
    assert "Do not swap scenarios between slots" in prompt
    assert "Speaker gender — MANDATORY" in prompt
    assert "ربعي" in prompt


@pytest.mark.parametrize(
    "gender,needle",
    [
        ("male", "Batch speaker gender: male"),
        ("female", "Batch speaker gender: female"),
        ("any", "Batch speaker gender: any / not specified"),
    ],
)
def test_build_user_prompt_speaker_gender_labels(gender, needle):
    from app.config import Settings

    prompt = llm_scripts.build_user_prompt(
        {
            "count": 4,
            "domains": ["billing"],
            "styles": ["neutral"],
            "languages": ["ar-AE"],
            "dialect": "emirati",
            "speaker_gender": gender,
        },
        Settings(),
    )
    assert needle in prompt


def test_system_prompt_documents_speaker_gender_rules():
    assert "Speaker gender — MANDATORY" in llm_scripts.SYSTEM_PROMPT
    assert 'speaker_gender is "male"' in llm_scripts.SYSTEM_PROMPT or "If speaker_gender is \"male\"" in llm_scripts.SYSTEM_PROMPT
    assert "female" in llm_scripts.SYSTEM_PROMPT
    assert "any" in llm_scripts.SYSTEM_PROMPT
    assert "ربيعاتي" in llm_scripts.SYSTEM_PROMPT
    assert "ربعي" in llm_scripts.SYSTEM_PROMPT


def test_build_user_prompt_includes_mandatory_gender_block():
    from app.config import Settings

    prompt = llm_scripts.build_user_prompt(
        {
            "count": 4,
            "domains": ["billing"],
            "styles": ["neutral"],
            "languages": ["ar-AE"],
            "dialect": "emirati",
            "speaker_gender": "male",
        },
        Settings(),
    )
    assert "Speaker gender — MANDATORY" in prompt
    assert "speaker_gender = male" in prompt
    assert "ربعي" in prompt
    assert "Do not switch to female-speaker wording" in prompt


def test_generate_params_speaker_gender_schema():
    from pydantic import ValidationError

    from app.schemas import GenerateParams

    assert GenerateParams().speaker_gender == "any"
    assert GenerateParams(speaker_gender="male").speaker_gender == "male"
    assert GenerateParams(speaker_gender="female").speaker_gender == "female"
    # Legacy aliases accepted and normalized.
    assert GenerateParams(speaker_gender="masculine").speaker_gender == "male"
    assert GenerateParams(speaker_gender="unspecified").speaker_gender == "any"
    with pytest.raises(ValidationError):
        GenerateParams(speaker_gender="other")


def test_generate_scripts_preserves_speaker_gender_on_retry(monkeypatch):
    """Regeneration / mini-batches must keep the selected gender constraint."""
    from app.config import Settings

    captured: list[dict] = []

    def fake_chat(client, settings, messages):
        # Second message is the user prompt carrying the gender value.
        captured.append({"system": messages[0]["content"], "user": messages[1]["content"]})
        return '{"items":[{"display_text":"مرحبا","training_text":"مرحبا","language":"ar-AE","dialect":"emirati","domain":"general","style":"neutral","tags":[]}]}'

    monkeypatch.setattr(llm_scripts, "_client", lambda settings, api_style="chat": object())
    monkeypatch.setattr(llm_scripts, "_generate_via_chat", fake_chat)
    monkeypatch.setattr(
        llm_scripts,
        "_generate_via_responses",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("force chat")),
    )

    settings = Settings()
    settings = settings.model_copy(update={"llm_api_style": "chat"})
    params = {
        "count": 1,
        "domains": ["general"],
        "styles": ["neutral"],
        "languages": ["ar-AE"],
        "dialect": "emirati",
        "speaker_gender": "female",
        "include_general": True,
    }
    llm_scripts.generate_scripts(params, settings)
    # Simulate regenerate with the same params object (UI regenerate path).
    llm_scripts.generate_scripts(params, settings)

    assert params["speaker_gender"] == "female"
    assert len(captured) == 2
    for turn in captured:
        assert "Batch speaker gender: female" in turn["user"]
        assert 'speaker_gender is "female"' in turn["system"]
        assert 'speaker_gender is "male"' in turn["system"]  # rules present
        assert "Speaker gender:" in turn["system"] or "speaker_gender" in turn["system"]


def test_build_user_prompt_uses_global_item_numbers_for_mini_batch():
    from app.config import Settings

    plan = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(10))
    prompt = llm_scripts.build_user_prompt(
        {
            "count": 5,
            "scenario_plan": scenario_planner.slice_plan(plan, 5, 5),
            "plan_offset": 5,
            "domains": ["billing"],
            "styles": ["neutral"],
            "languages": ["ar-AE"],
            "dialect": "emirati",
        },
        Settings(),
    )
    assert "ITEM 6\n" in prompt or prompt.split("ITEM 6")[0].endswith("\n")
    assert "ITEM 10" in prompt
    assert "\nITEM 1\n" not in prompt


def test_build_retry_prompt_includes_required_scenario(monkeypatch):
    from app.config import Settings

    slot = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(1))[0]
    slot["scenario"] = "esim_transfer"
    slot["intent"] = "Customer wants to move their existing number from a physical SIM to an eSIM."
    prompt = llm_scripts.build_retry_user_prompt(
        slot,
        {"speaker_gender": "male", "dialect": "emirati"},
        Settings(),
        ["scenario mismatch: expected 'esim_transfer', got 'sim_activation'"],
    )
    assert "Required scenario: esim_transfer" in prompt
    assert "physical SIM to an eSIM" in prompt
    assert "Do not change the scenario" in prompt


def test_regenerate_single_item_only_one_slot(monkeypatch):
    from app.config import Settings

    slot = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(1))[0]
    captured: list[str] = []

    def fake_call(messages, *, settings, count):
        captured.append(messages[1]["content"])
        scenario_tag = slot["scenario"]
        return json.dumps(
            {
                "items": [
                    {
                        "display_text": "ابا أنقل رقمي ل eSIM",
                        "training_text": "ابا أنقل رقمي ل eSIM",
                        "language": "ar-AE",
                        "dialect": "emirati",
                        "domain": slot["domain"],
                        "style": slot["style"],
                        "tags": [f"scenario:{scenario_tag}"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_scripts, "_call_llm_messages", fake_call)
    item = llm_scripts.regenerate_single_item(
        slot,
        {"speaker_gender": "male", "dialect": "emirati"},
        Settings(),
        ["scenario mismatch"],
    )
    assert captured
    assert slot["scenario"] in captured[0]
    assert item["tags"] == [f"scenario:{slot['scenario']}"]


def test_generate_validated_items_retries_only_failed_slot(monkeypatch):
    from app.config import Settings

    plan = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(2))
    calls = {"generate": 0, "retry": 0}

    def fake_generate(params, settings):
        calls["generate"] += 1
        return [
            {
                "display_text": "النت بطيء عندي",
                "training_text": "النت بطيء عندي",
                "language": plan[0]["language"],
                "dialect": plan[0]["dialect"],
                "domain": plan[0]["domain"],
                "style": plan[0]["style"],
                "tags": [f"scenario:{plan[1]['scenario']}"],
            },
            {
                "display_text": "الجملة الثانية صحيحة",
                "training_text": "الجملة الثانية صحيحة",
                "language": plan[1]["language"],
                "dialect": plan[1]["dialect"],
                "domain": plan[1]["domain"],
                "style": plan[1]["style"],
                "tags": [f"scenario:{plan[1]['scenario']}"],
            },
        ]

    def fake_retry(slot, params, settings, errors):
        calls["retry"] += 1
        return {
            "display_text": "تم إصلاح السيناريو الأول",
            "training_text": "تم إصلاح السيناريو الأول",
            "language": slot["language"],
            "dialect": slot["dialect"],
            "domain": slot["domain"],
            "style": slot["style"],
            "tags": [f"scenario:{slot['scenario']}"],
        }

    monkeypatch.setattr(llm_scripts, "generate_scripts", fake_generate)
    monkeypatch.setattr(llm_scripts, "regenerate_single_item", fake_retry)

    results = llm_scripts.generate_validated_items(
        {"count": 2, "speaker_gender": "any", "scenario_plan": plan},
        Settings(),
        plan,
        existing_hashes=set(),
        existing_texts=[],
        batch_hashes=set(),
        batch_scenario_ids=set(),
    )
    assert calls["generate"] == 1
    assert calls["retry"] == 1
    assert results[0]["ok"] is True
    assert results[1]["ok"] is True
    assert results[0]["computed"]["training_text"] == "تم إصلاح السيناريو الأول"


def test_numeric_time_variants_are_near_duplicates():
    a = "بدل حجزي من الساعة 8 للساعة 9:30"
    b = "بدل حجزي من الساعة ثمان للساعة تسع ونص"
    assert llm_scripts.is_near_duplicate(a, b)


def test_validate_item_rejects_domain_mismatch_with_slot():
    slot = scenario_planner.plan_as_dicts(scenario_planner.plan_generation_batch(1))[0]
    result = llm_scripts.validate_planned_item(
        {
            "display_text": "النت بطيء",
            "training_text": "النت بطيء",
            "language": slot["language"],
            "dialect": slot["dialect"],
            "style": slot["style"],
            "domain": "general",
            "tags": [f"scenario:{slot['scenario']}"],
        },
        slot,
        existing_hashes=set(),
        existing_texts=[],
        batch_hashes=set(),
    )
    if slot["domain"] != "general":
        assert result["ok"] is False
        assert any("domain mismatch" in e for e in result["errors"])


def test_gender_propagates_from_params_into_plan():
    params = {
        "count": 6,
        "domains": ["billing", "telecom"],
        "speaker_gender": "female",
        "languages": ["ar-AE"],
        "dialect": "emirati",
        "styles": ["neutral"],
    }
    plan = llm_scripts.ensure_scenario_plan(params)
    assert all(s["speaker_gender"] == "female" for s in plan)


def test_validate_item_rejects_duplicate_scenario_in_batch():
    batch_scenario_ids: set[str] = set()
    first = llm_scripts.validate_item(
        {
            "display_text": "باقي لي كم يوم إجازة؟",
            "language": "ar-AE",
            "dialect": "emirati",
            "domain": "hr",
            "tags": ["scenario:hr_leave_balance"],
        },
        set(),
        [],
        set(),
        batch_scenario_ids=batch_scenario_ids,
        expected_scenario="hr_leave_balance",
    )
    second = llm_scripts.validate_item(
        {
            "display_text": "كم باقي من إجازتي السنوية؟",
            "language": "ar-AE",
            "dialect": "emirati",
            "domain": "hr",
            "tags": ["scenario:hr_leave_balance"],
        },
        set(),
        [],
        set(),
        batch_scenario_ids=batch_scenario_ids,
        expected_scenario="hr_leave_balance",
    )
    assert first["ok"] is True
    assert second["ok"] is False
    assert any("duplicate scenario" in e for e in second["errors"])


def test_validate_item_rejects_scenario_mismatch():
    result = llm_scripts.validate_item(
        {
            "display_text": "النت بطيء عندي",
            "language": "ar-AE",
            "dialect": "emirati",
            "domain": "technical_support",
            "tags": ["scenario:slow_internet"],
        },
        set(),
        [],
        set(),
        expected_scenario="weak_signal",
    )
    assert result["ok"] is False
    assert any("scenario mismatch" in e for e in result["errors"])


def test_validate_batch_diversity_rejects_duplicate_scenario_tags():
    items = [
        {"domain": "billing", "tags": ["scenario:unexpected_invoice"]},
        {"domain": "billing", "tags": ["scenario:unexpected_invoice"]},
    ]
    issues = scenario_planner.validate_batch_diversity(items)
    assert any("duplicate scenario" in i for i in issues)


def test_validate_batch_diversity_flags_concentration():
    items = [
        {"domain": "billing", "tags": ["scenario:unexpected_invoice"]}
        for _ in range(12)
    ]
    issues = scenario_planner.validate_batch_diversity(items)
    assert issues
    assert any("distinct scenarios" in i or "general domain ratio" in i for i in issues)


def test_validate_batch_diversity_accepts_balanced_batch():
    plan = scenario_planner.plan_generation_batch(20)
    items = [
        {
            "domain": s.domain,
            "tags": [f"scenario:{s.scenario}"],
        }
        for s in plan
    ]
    assert scenario_planner.validate_batch_diversity(items) == []


# ---------------------------------------------------------------------------
# D. Near-duplicate detection
# ---------------------------------------------------------------------------

def test_exact_duplicate_rejected():
    from app.services import text_normalize as tn

    text = "أبا أشيك على باقة النت"
    batch_hashes: set[str] = set()
    texts: list[str] = []
    hashes: set[str] = set()
    first = llm_scripts.validate_item(
        {"display_text": text, "language": "ar-AE", "dialect": "emirati"},
        hashes,
        texts,
        batch_hashes,
    )
    assert first["ok"] is True
    hashes.add(tn.normalized_hash(first["computed"]["training_text"]))
    second = llm_scripts.validate_item(
        {"display_text": text, "language": "ar-AE", "dialect": "emirati"},
        hashes,
        texts,
        batch_hashes,
    )
    assert second["ok"] is False
    assert any("duplicate" in e for e in second["errors"])


def test_near_paraphrase_net_package_is_duplicate():
    a = "أبغي أشيك على باقة النت"
    b = "أريد أتحقق من باقة الإنترنت"
    assert llm_scripts.is_near_duplicate(a, b)


def test_unrelated_utterances_are_not_duplicates():
    a = "أبغي أشيك على باقة النت"
    b = "وين أقرب فرع عندكم؟"
    assert not llm_scripts.is_near_duplicate(a, b)


def test_near_duplicate_within_batch_is_error():
    texts: list[str] = []
    hashes: set[str] = set()
    batch: set[str] = set()
    first = llm_scripts.validate_item(
        {
            "display_text": "أبغي أشيك على باقة النت",
            "language": "ar-AE",
            "dialect": "emirati",
        },
        hashes,
        texts,
        batch,
    )
    second = llm_scripts.validate_item(
        {
            "display_text": "أريد أتحقق من باقة الإنترنت",
            "language": "ar-AE",
            "dialect": "emirati",
        },
        hashes,
        texts,
        batch,
    )
    assert first["ok"] is True
    assert second["ok"] is False
    assert any("near-duplicate" in e for e in second["errors"])


def test_short_shared_telecom_terms_alone_do_not_collide():
    a = "الرصيد خلص"
    b = "الفاتورة وصلت"
    assert not llm_scripts.is_near_duplicate(a, b)

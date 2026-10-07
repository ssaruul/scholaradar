from scholaradar.llm.schema import Opportunity
from scholaradar.llm.verify import deterministic_override, evidence_in_text, verify

NAMES = ["Mongolia", "Mongolian", "Монголия", "Монголии", "モンゴル", "몽골", "蒙古"]


def make(**overrides: object) -> Opportunity:
    base = dict(
        is_opportunity=True,
        title="Test Scholarship",
        canonical_name="Test Scholarship",
        provider="Test Foundation",
        host_country="Japan",
        degree_levels=["master"],
        fields_of_study=[],
        funding_type="full",
        deadline="2027-01-15",
        deadline_text="15 January 2027",
        eligibility_summary="Open to students from developing countries.",
        nationality_mode="region",
        target_eligible="yes",
        evidence_quote="Applicants must be nationals of a developing country listed in Annex A.",
        apply_url="",
    )
    base.update(overrides)
    return Opportunity.model_validate(base)


def test_evidence_matches_despite_whitespace_and_case() -> None:
    text = "Eligibility:\n  Applicants must be nationals of a developing   country listed in Annex A.\nDeadline soon."
    assert evidence_in_text("applicants must be nationals of a developing country listed in annex a", text)


def test_evidence_rejects_paraphrase_and_short_quotes() -> None:
    text = "Applicants must be nationals of a developing country listed in Annex A."
    assert not evidence_in_text("Nationals of developing countries can apply.", text)
    assert not evidence_in_text("Annex A", text)


def test_unverified_yes_becomes_unclear() -> None:
    opp, verified = verify(make(evidence_quote="Mongolians are welcome to apply."), "This page says nothing about nationality.", NAMES)
    assert not verified
    assert opp.target_eligible == "unclear"


def test_verified_yes_stays() -> None:
    text = "Applicants must be nationals of a developing country listed in Annex A."
    opp, verified = verify(make(), text, NAMES)
    assert verified
    assert opp.target_eligible == "yes"


def test_explicit_list_overrides_model_unclear() -> None:
    text = "Eligible countries: Kazakhstan, Kyrgyzstan, Mongolia, Uzbekistan and Viet Nam. Deadline 1 March."
    opp, verified = verify(make(target_eligible="unclear", nationality_mode="unclear", evidence_quote=""), text, NAMES)
    assert verified
    assert opp.target_eligible == "yes"
    assert "Mongolia" in opp.evidence_quote
    assert opp.nationality_mode == "list"


def test_explicit_exclusion_overrides_model_yes() -> None:
    text = "Open to all Asian countries. Citizens of Mongolia and China are not eligible for this round."
    opp, verified = verify(make(evidence_quote="Open to all Asian countries."), text, NAMES)
    assert verified
    assert opp.target_eligible == "no"


def test_override_none_when_ambiguous() -> None:
    text = "Students from Mongolia are eligible, except those already holding a Japanese scholarship. Mongolia is excluded from track B."
    assert deterministic_override(text, NAMES) is None


def test_override_multilingual_inclusion() -> None:
    assert deterministic_override("対象国：モンゴル、ベトナム、ラオス", NAMES).verdict == "yes"
    assert deterministic_override("지원 자격: 몽골 국적 소지자", NAMES).verdict == "yes"
    assert deterministic_override("Граждане Монголии могут подать заявку.", NAMES).verdict == "yes"


def test_destination_mention_is_not_inclusion() -> None:
    text = "До 29 мая 2026 года российские студенты могут подать документы на стипендию Правительства Монголии. Обучение пройдет в монгольских университетах."
    assert deterministic_override(text, NAMES + ["Монголии"]) is None
    text_zh = "升学地点包括葡萄牙、巴西、马来西亚、匈牙利或蒙古，申请人须为澳门永久性居民。"
    assert deterministic_override(text_zh, NAMES) is None


def test_one_country_per_line_list() -> None:
    text = "Eligible countries\nKazakhstan\nKyrgyzstan\nLao PDR\nMongolia\nNepal\nPakistan\nDeadline: 1 March 2027."
    override = deterministic_override(text, NAMES)
    assert override is not None and override.verdict == "yes"


def test_one_country_per_line_exclusion_header() -> None:
    text = "The following countries are not eligible:\nChina\nIndia\nMongolia\nRussia\nTurkey\nVietnam\nDeadline: 1 March 2027."
    override = deterministic_override(text, NAMES)
    assert override is not None and override.verdict == "no"

from __future__ import annotations

import re
from dataclasses import dataclass

from ..prefilter import sentences_mentioning
from .schema import Opportunity

NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

EXCLUSION_CUES = (
    "not eligible", "ineligible", "excluded", "cannot apply", "may not apply", "are not accepted", "with the exception of", "except for",
    "не могут", "не имеют права", "за исключением", "не принимаются",
    "対象外", "除く", "を除き", "応募できません",
    "제외", "지원할 수 없", "불가",
    "除外", "不包括", "不得申请", "不接受",
    "ausgeschlossen", "ausgenommen", "nicht berechtigt", "nicht bewerben",
    "hariç", "başvuramaz",
    "хамаарахгүй", "боломжгүй",
)

INCLUSION_CUES = (
    "eligible", "open to", "citizen", "national", "countries", "applicants from", "students from", "including", "country list", "list of countries",
    "граждан", "стран", "могут", "студентов из", "для студентов",
    "対象", "国籍", "出身", "国・地域", "募集対象",
    "대상", "국적", "국가", "자격",
    "国籍", "国家", "申请人", "资格", "来自",
    "staatsangehörig", "länder", "berechtigt", "bewerben können",
    "vatandaş", "ülke", "başvurabilir",
    "иргэн", "улс", "оролцох", "хамрагдах", "боломжтой",
)


def normalize(text: str) -> str:
    return NON_WORD.sub(" ", text.casefold()).strip()


def evidence_in_text(quote: str, text: str) -> bool:
    needle = normalize(quote)
    if len(needle) < 12:
        return False
    return needle in normalize(text)


@dataclass(frozen=True)
class Override:
    verdict: str
    sentence: str


def deterministic_override(text: str, names: list[str]) -> Override | None:
    sentences = sentences_mentioning(text, names)
    if not sentences:
        return None
    excluding = [s for s in sentences if any(cue in s.casefold() for cue in EXCLUSION_CUES)]
    including = [s for s in sentences if s not in excluding and any(cue in s.casefold() for cue in INCLUSION_CUES)]
    if excluding and not including:
        return Override("no", excluding[0])
    if excluding:
        return None
    if including:
        return Override("yes", including[0])
    return None


def verify(opp: Opportunity, text: str, names: list[str]) -> tuple[Opportunity, bool]:
    verified = bool(opp.evidence_quote) and evidence_in_text(opp.evidence_quote, text)
    updates: dict[str, object] = {}
    if not verified and opp.target_eligible != "unclear":
        updates["target_eligible"] = "unclear"
    override = deterministic_override(text, names)
    if override is not None:
        updates["target_eligible"] = override.verdict
        if not verified or opp.target_eligible != override.verdict:
            updates["evidence_quote"] = override.sentence[:500]
        verified = True
        if opp.nationality_mode == "unclear":
            updates["nationality_mode"] = "list"
    return opp.model_copy(update=updates), verified

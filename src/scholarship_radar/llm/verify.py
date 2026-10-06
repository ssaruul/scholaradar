from __future__ import annotations

import re
from dataclasses import dataclass

from ..prefilter import sentences_mentioning
from .schema import Opportunity

NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
LIST_SEPARATORS = re.compile(r"[,;、，；]")

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

CITIZENSHIP_CUES = (
    "citizen", "national", "passport holder", "students from", "applicants from", "candidates from", "researchers from",
    "граждан", "гражданство",
    "国籍", "出身",
    "국적",
    "公民", "国籍",
    "staatsangehörig", "staatsbürger",
    "vatandaş",
    "иргэн", "иргэд",
)

DESTINATION_PREFIXES = ("in ", "to ", "at ", "в ", "во ", "на ", "study in", "studying in", "обучение в", "обучения в", "留学", "赴")

DESTINATION_SENTENCE_CUES = (
    "study in", "studying in", "destination", "host countr", "host institution", "universities in", "placement in",
    "обучение в", "обучения в", "стажировк", "страны обучения",
    "留学先", "派遣先", "渡航先",
    "유학 국가", "파견국", "유학지",
    "升学地点", "留学地", "目的地", "赴外", "前往",
    "studienland", "gastland",
    "суралцах улс",
)

LIST_HEADER_CUES = (
    "eligible countries", "countries", "nationals of", "citizens of", "country list", "open to",
    "страны", "граждане", "гражданам",
    "対象国", "国・地域", "対象",
    "국가", "대상국", "국적",
    "国家", "国籍",
    "länder", "staatsangehörige",
    "ülkeler", "vatandaşları",
    "улс", "иргэд",
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


def _name_positions(sentence: str, names: list[str]) -> list[tuple[int, int]]:
    folded = sentence.casefold()
    positions = []
    for name in names:
        start = folded.find(name.casefold())
        while start != -1:
            positions.append((start, start + len(name)))
            start = folded.find(name.casefold(), start + 1)
    return positions


def _is_destination(sentence: str, start: int) -> bool:
    before = sentence[max(0, start - 12):start].casefold()
    return any(before.endswith(prefix) for prefix in DESTINATION_PREFIXES)


def looks_like_country_list(sentence: str) -> bool:
    items = [item.strip() for item in LIST_SEPARATORS.split(sentence) if item.strip()]
    has_header = any(cue in sentence.casefold() for cue in LIST_HEADER_CUES)
    if len(items) < (3 if has_header else 5):
        return False
    short_items = sum(1 for item in items if len(item) <= 40)
    return short_items >= len(items) * 0.75


def _has_citizenship_cue_nearby(sentence: str, start: int, end: int) -> bool:
    window = sentence[max(0, start - 30):min(len(sentence), end + 30)].casefold()
    return any(cue in window for cue in CITIZENSHIP_CUES)


def _list_item_context(text: str, names: list[str]) -> Override | None:
    lines = [line.strip() for line in text.splitlines()]
    folded_names = [name.casefold() for name in names]
    for index, line in enumerate(lines):
        if len(line) > 40 or not any(name in line.casefold() for name in folded_names):
            continue
        neighbours = [other for other in lines[max(0, index - 4):index + 5] if other]
        if sum(1 for other in neighbours if len(other) <= 30) < 5:
            continue
        heading = " ".join(lines[max(0, index - 8):index]).casefold()
        verdict = "no" if any(cue in heading for cue in EXCLUSION_CUES) else "yes"
        return Override(verdict, " ".join(other for other in neighbours if other)[:500])
    return None


def deterministic_override(text: str, names: list[str]) -> Override | None:
    sentences = sentences_mentioning(text, names)
    if not sentences:
        return None
    excluding = [s for s in sentences if any(cue in s.casefold() for cue in EXCLUSION_CUES)]
    including = []
    list_item = _list_item_context(text, names)
    if list_item is not None:
        if list_item.verdict == "no":
            excluding.append(list_item.sentence)
        else:
            including.append(list_item.sentence)
    for sentence in sentences:
        if sentence in excluding:
            continue
        destination_sentence = any(cue in sentence.casefold() for cue in DESTINATION_SENTENCE_CUES)
        for start, end in _name_positions(sentence, names):
            if _is_destination(sentence, start):
                continue
            if _has_citizenship_cue_nearby(sentence, start, end) or (looks_like_country_list(sentence) and not destination_sentence):
                including.append(sentence)
                break
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

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from urllib.parse import urlsplit

from ..urls import canonicalize, host_of

TITLE_NOISE = re.compile(r"\b(20\d\d(?:\s*[-/–]\s*(?:20)?\d\d)?|scholarships?|fellowships?|programme|program|grants?|for|in|at|the|of|and|to|a|an|international|students?|citizens?|applications?|open|now|call|annual|awards?|bewerbung|notice|announcement|guidelines?|information|оны|онд|хичээлийн|жилийн|жилд|засгийн|газрын|улсын|улс|тэтгэлэг|тэтгэлэгт|хөтөлбөр|хөтөлбөрт|стипендия|стипендии)\b", re.I)
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]+")
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
VERDICT_RANK = {"yes": 0, "unclear": 1, "no": 2}
SHARED_PORTALS = ("campuschina.org", "csc.edu.cn", "studyinkorea.go.kr", "apply.iie.org", "esis.edu.mn", "turkiyeburslari.gov.tr", "stipendiumhungaricum.hu", "daad.de", "jasso.go.jp", "mext.go.jp", "studyinjapan.go.jp", "chevening.org")
OFFICIAL_HOST = re.compile(r"(^|\.)(gov|go|edu|ac|mil|gc)\.[a-z]+$|\.(gov|edu|int)$|^(embassy|consulate)\.")
OFFICIAL_HOSTS = ("chevening.org", "jds-scholarship.org", "australiaawardsmongolia.org", "stipendiumhungaricum.hu", "daad.de", "fulbrightprogram.org", "iie.org", "worldbank.org", "adb.org", "unesco.org", "jica.go.jp", "koica.go.kr", "nawa.gov.pl", "sbfi.admin.ch", "icdf.org.tw", "studyintaiwan.org", "studyinsweden.se", "campusfrance.org", "erasmus-plus.ec.europa.eu", "ec.europa.eu")
AGGREGATOR_HOSTS = ("scholars4dev", "opportunitydesk", "haniseoul", "global-generations", "studyu", "educations.com", "selfstartglobal", "gaxi.jp", "scholarshiptab", "scholarshipbob", "mastersportal", "fundsforngos")


def title_tokens(title: str) -> frozenset[str]:
    head = title.split("|")[0].split(" - ")[0]
    cleaned = TITLE_NOISE.sub(" ", head)
    tokens: set[str] = set()
    for run in CJK.findall(cleaned):
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    latin = CJK.sub(" ", cleaned).casefold()
    tokens.update(WORD.findall(latin))
    return frozenset(tokens)


def _apply_key(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if any(host == portal or host.endswith("." + portal) for portal in SHARED_PORTALS):
        return ""
    if parts.path.strip("/") == "" and not parts.query:
        return ""
    return canonicalize(url)


def _compatible_country(a: dict, b: dict) -> bool:
    return len({a["host_country"], b["host_country"]} - {""}) <= 1


def is_official(url: str) -> bool:
    host = host_of(url)
    bare = host[4:] if host.startswith("www.") else host
    if any(bare == known or bare.endswith("." + known) for known in OFFICIAL_HOSTS + SHARED_PORTALS):
        return True
    if any(agg in bare for agg in AGGREGATOR_HOSTS):
        return False
    return bool(OFFICIAL_HOST.search(bare))


def _priority(row: dict, today: str) -> tuple:
    official = is_official(row["page_url"])
    deadline = row["deadline"] or ""
    deadline_rank = 0 if deadline >= today and deadline else (1 if not deadline else 2)
    return (row.get("lang") != "en", not official, deadline_rank, not row["evidence_verified"], VERDICT_RANK.get(row["target_eligible"], 3), -len(row["eligibility_summary"] or ""))


def _canonical_key(row: dict) -> frozenset[str]:
    name = (row.get("canonical_name") or "").strip()
    return title_tokens(name) if name else frozenset()


def _merge_verdict(representative: dict, members: list[dict], today: str) -> None:
    verified = [m for m in members if m["evidence_verified"]]
    yes = [m for m in verified if m["target_eligible"] == "yes"]
    no = [m for m in verified if m["target_eligible"] == "no"]
    chosen = yes[0] if yes else (no[0] if no and not any(m["target_eligible"] == "yes" for m in members) else None)
    if chosen is not None and (representative["target_eligible"] != chosen["target_eligible"] or not representative["evidence_verified"]):
        representative["target_eligible"] = chosen["target_eligible"]
        representative["evidence_quote"] = chosen["evidence_quote"]
        representative["evidence_verified"] = True
        representative["nationality_mode"] = chosen["nationality_mode"]
    elif chosen is None and representative["target_eligible"] == "no" and any(m["target_eligible"] != "no" for m in members):
        representative["target_eligible"] = "unclear"
    upcoming = sorted(m["deadline"] for m in members if m["deadline"] and m["deadline"] >= today)
    if upcoming and (not representative["deadline"] or representative["deadline"] < today or representative["deadline"] > upcoming[0]):
        representative["deadline"] = upcoming[0]
        source = next(m for m in members if m["deadline"] == upcoming[0])
        representative["deadline_text"] = source["deadline_text"]


def group_opportunities(rows: list[dict], today: date | None = None) -> list[dict]:
    today_text = (today or date.today()).isoformat()
    tokens = [title_tokens(row["title"]) for row in rows]
    canonical = [_canonical_key(row) for row in rows]
    frequency = Counter(token for token_set in tokens for token in token_set)
    distinctive_limit = max(3, len(rows) // 100)
    distinctive = [frozenset(token for token in token_set if frequency[token] <= distinctive_limit) for token_set in tokens]
    apply_keys = [_apply_key(row["apply_url"]) for row in rows]

    def same(i: int, j: int) -> bool:
        if apply_keys[i] and apply_keys[i] == apply_keys[j]:
            return True
        if not _compatible_country(rows[i], rows[j]):
            return False
        if canonical[i] and canonical[i] == canonical[j]:
            return True
        if not tokens[i] or not tokens[j]:
            return False
        if tokens[i] == tokens[j]:
            return True
        if not distinctive[i] or not distinctive[j]:
            return False
        shared = len(distinctive[i] & distinctive[j])
        return shared / len(distinctive[i] | distinctive[j]) >= 0.5

    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if find(i) != find(j) and same(i, j):
                parent[find(j)] = find(i)
    groups: dict[int, list[dict]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    merged = []
    for members in groups.values():
        members.sort(key=lambda row: _priority(row, today_text))
        representative = dict(members[0])
        _merge_verdict(representative, members, today_text)
        representative["group_ids"] = [member["id"] for member in members]
        representative["also_on"] = [{"title": member["title"], "url": member["page_url"]} for member in members[1:]]
        merged.append(representative)
    merged.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or "", r["first_seen"]))
    return merged

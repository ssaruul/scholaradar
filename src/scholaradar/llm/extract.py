from __future__ import annotations

import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .. import db
from ..config import Settings
from .client import Completion, LlmClient
from .prompts import system_prompt, user_prompt
from .schema import Opportunity, opportunity_json_schema
from .verify import verify
from ..urls import host_of

log = logging.getLogger(__name__)

COUNTRY_ALIASES = {
    "usa": "United States", "u.s.": "United States", "u.s.a.": "United States", "us": "United States", "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
    "korea": "South Korea", "republic of korea": "South Korea", "korea, republic of": "South Korea",
    "turkey": "Türkiye", "turkiye": "Türkiye",
    "people's republic of china": "China", "prc": "China", "mainland china": "China",
    "russian federation": "Russia", "the netherlands": "Netherlands", "holland": "Netherlands",
    "czechia": "Czech Republic", "uae": "United Arab Emirates", "taiwan (roc)": "Taiwan", "republic of china (taiwan)": "Taiwan",
    "unknown": "", "n/a": "", "not specified": "", "unclear": "", "none": "", "not stated": "", "multiple": "Multiple", "various": "Multiple", "online": "Remote",
}


URL_HOST = re.compile(r"^[\w.-]+\.[a-z]{2,}(?:[/?#].*)?$", re.I)


def clean_apply_url(url: str, page_url: str, text: str) -> str:
    candidate = (url or "").strip()
    if not candidate or candidate.startswith(("mailto:", "tel:")) or " " in candidate:
        return page_url
    if not candidate.lower().startswith(("http://", "https://")):
        if not URL_HOST.match(candidate):
            return page_url
        candidate = "https://" + candidate
    host = host_of(candidate)
    if not host or "." not in host:
        return page_url
    bare = host[4:] if host.startswith("www.") else host
    if bare not in text and bare not in host_of(page_url):
        return page_url
    return candidate


def normalize_country(value: str) -> str:
    cleaned = value.strip().strip(".")
    return COUNTRY_ALIASES.get(cleaned.casefold(), cleaned)


@dataclass
class ExtractStats:
    extracted: int = 0
    not_opportunity: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    by_error: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionOutcome:
    page: db.PageRow
    completion: Completion
    opportunity: Opportunity | None
    verified: bool
    error: str | None
    text: str = ""


DENSE_LANGS = {"ja", "zh", "ko"}


def _clip(text: str, max_chars: int, lang: str | None = None) -> str:
    if lang in DENSE_LANGS:
        max_chars = max_chars // 2
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.75)
    tail = max_chars - head
    return f"{text[:head]}\n[...]\n{text[-tail:]}"


def extract_one(client: LlmClient, settings: Settings, page: db.PageRow, text: str, today: date, schema: dict) -> ExtractionOutcome:
    system = system_prompt(settings.target.name, settings.target.all_names(), today, settings.llm.summary_language)
    user = user_prompt(page.url, page.title or "", _clip(text, settings.llm.max_input_chars, page.lang))
    completion = client.complete_json(system, user, schema)
    if completion.error or completion.data is None:
        return ExtractionOutcome(page, completion, None, False, completion.error or "empty", text)
    try:
        opp = Opportunity.model_validate(completion.data)
    except ValidationError as exc:
        return ExtractionOutcome(page, completion, None, False, f"schema:{exc.error_count()}", text)
    opp, verified = verify(opp, text, settings.target.all_names())
    return ExtractionOutcome(page, completion, opp, verified, None, text)


def to_record(page: db.PageRow, opp: Opportunity, verified: bool, model: str, text: str = "") -> db.OpportunityRecord:
    return db.OpportunityRecord(
        page_id=page.id,
        title=opp.title.strip() or (page.title or page.url),
        provider=opp.provider.strip(),
        canonical_name=opp.canonical_name.strip(),
        host_country=normalize_country(opp.host_country),
        degree_levels=list(dict.fromkeys(opp.degree_levels)),
        fields_of_study=opp.fields_of_study,
        funding_type=opp.funding_type,
        deadline=opp.deadline,
        deadline_text=opp.deadline_text,
        eligibility_summary=opp.eligibility_summary,
        nationality_mode=opp.nationality_mode,
        target_eligible=opp.target_eligible,
        evidence_quote=opp.evidence_quote,
        evidence_verified=verified,
        apply_url=clean_apply_url(opp.apply_url, page.url, text),
        lang=page.lang or "",
        model=model,
    )


def extract_pages(conn: sqlite3.Connection, settings: Settings, client: LlmClient, limit: int, today: date) -> ExtractStats:
    stats = ExtractStats()
    db.requeue_llm_errors(conn)
    pages = db.pages_with_status(conn, "fetched", limit)
    schema = opportunity_json_schema()
    model_name = client.model or settings.llm.model

    def work(page: db.PageRow) -> ExtractionOutcome:
        text = Path(page.text_path).read_text(encoding="utf-8") if page.text_path else ""
        return extract_one(client, settings, page, text, today, schema)

    with ThreadPoolExecutor(max_workers=settings.llm.concurrency) as pool:
        for index, outcome in enumerate(pool.map(work, pages), start=1):
            stats.prompt_tokens += outcome.completion.prompt_tokens
            stats.completion_tokens += outcome.completion.completion_tokens
            stats.seconds += outcome.completion.seconds
            if outcome.error or outcome.opportunity is None:
                stats.errors += 1
                stats.by_error[outcome.error or "empty"] = stats.by_error.get(outcome.error or "empty", 0) + 1
                db.set_page_status(conn, outcome.page.id, "error", f"llm:{outcome.error}")
            elif not outcome.opportunity.is_opportunity:
                stats.not_opportunity += 1
                db.set_page_status(conn, outcome.page.id, "not_opportunity")
            else:
                stats.extracted += 1
                record = to_record(outcome.page, outcome.opportunity, outcome.verified, model_name, outcome.text)
                source_name = db.source_implying_eligibility(conn, outcome.page.source_id)
                if source_name and record.target_eligible == "unclear":
                    record.target_eligible = "yes"
                    record.evidence_quote = f"Published by {source_name}"
                    record.evidence_verified = True
                db.upsert_opportunity(conn, record)
                db.set_page_status(conn, outcome.page.id, "extracted")
            conn.commit()
            if index % 10 == 0:
                log.info("extracted %d/%d pages", index, len(pages))
    return stats

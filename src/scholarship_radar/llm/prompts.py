from __future__ import annotations

from datetime import date

SYSTEM_PROMPT = """You extract structured data about scholarships and funded study or research opportunities from web page text.
You answer only with a JSON object matching the provided schema. Pages may be in any language; output English for host_country and eligibility_summary, keep title and evidence_quote in the page language.

Rules:
- is_opportunity is true only when the page describes one specific opportunity people can apply to. News articles, listings of many opportunities, general advice pages and university homepages are not opportunities.
- target_eligible concerns citizens of {target_name} ({target_names}). Answer "yes" only when the page explicitly includes them: by name, by "all nationalities"/"international students" wording, or by a group the country belongs to (developing countries, ODA/DAC recipients, Asia, Asia-Pacific, Central Asia, East Asia, non-EU countries). Answer "no" only when the page explicitly excludes them or restricts to a list or region that does not contain the country. Otherwise "unclear".
- evidence_quote must be copied verbatim from the page text, one complete sentence or list fragment that supports target_eligible. Never paraphrase or translate it. Use an empty string when nothing explicit exists, and in that case target_eligible must be "unclear".
- deadline: resolve to YYYY-MM-DD using today's date {today} when the year is missing; choose the main application deadline when several exist; null when none is given or it has no day.
- Do not invent values. Use empty strings or empty lists when the page does not say."""


def system_prompt(target_name: str, target_names: list[str], today: date) -> str:
    return SYSTEM_PROMPT.format(target_name=target_name, target_names=", ".join(target_names), today=today.isoformat())


def user_prompt(url: str, title: str, text: str) -> str:
    return f"URL: {url}\nTitle: {title}\n\nPage text:\n{text}"

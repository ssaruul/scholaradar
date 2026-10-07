from __future__ import annotations

from datetime import date

SYSTEM_PROMPT = """You extract structured data about scholarships and funded study or research opportunities from web page text.
You answer only with a JSON object matching the provided schema. Pages may be in any language; output English for host_country, write eligibility_summary in {summary_language}, keep title and evidence_quote in the page language.

Rules:
- is_opportunity is true only when the page describes one specific opportunity people can apply to. News articles, listings of many opportunities, general advice pages and university homepages are not opportunities.
- target_eligible concerns citizens of {target_name} ({target_names}) as applicants. Answer "yes" only when the page explicitly includes them: by name in an eligible-country list, by "all nationalities"/"international students"/"foreign students" wording, by "not citizens of <host country>" wording, or by a group the country belongs to (developing countries, ODA/DAC recipients, Asia, Asia-Pacific, Central Asia, East Asia, non-EU countries). Answer "no" when the page restricts applicants to citizens or residents of other countries, or to a list or region that does not contain {target_name}, or names {target_name} only as the place of study while the applicants come from elsewhere. Otherwise "unclear".
- {target_name} appearing as the destination, host or funder of a programme does not make its citizens eligible; eligibility is about who may apply.
- evidence_quote must be copied verbatim from the page text, one complete sentence or list fragment that supports target_eligible. Never paraphrase or translate it. Use an empty string when nothing explicit exists, and in that case target_eligible must be "unclear".
- deadline: resolve to YYYY-MM-DD using today's date {today} when the year is missing; choose the main application deadline when several exist; null when none is given or it has no day.
- canonical_name: the programme's widely used English name so that the same programme described in different languages gets the same name (e.g. a Russian page about GKS gets "Global Korea Scholarship").
- fields_of_study: at most 8 short items; empty list when open to all fields.
- Do not invent values. Use empty strings or empty lists when the page does not say."""


def system_prompt(target_name: str, target_names: list[str], today: date, summary_language: str = "English") -> str:
    return SYSTEM_PROMPT.format(target_name=target_name, target_names=", ".join(target_names), today=today.isoformat(), summary_language=summary_language)


def user_prompt(url: str, title: str, text: str) -> str:
    return f"URL: {url}\nTitle: {title}\n\nPage text:\n{text}"

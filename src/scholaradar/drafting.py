from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .llm.client import LlmClient

KINDS = ("email", "research_plan", "sop", "cv")
LANGUAGE_NAMES = {"en": "English", "ja": "Japanese", "mn": "Mongolian"}

SYSTEM = """You help a student from {target} prepare a scholarship or graduate-school application. Write in {language}. Use only facts given in the profile and context; where a fact is missing, leave a clearly marked placeholder like [ADD: your GPA]. Be specific, concrete and modest in tone; no flattery, no filler, no emoji. Write people's names exactly as given in the context (romanised if given romanised); never guess kanji, hanja or other spellings for a name, and never invent paper titles, dates, numbers or affiliations."""

INSTRUCTIONS = {
    "email": """Write a first email to Professor {professor} asking whether they would consider supervising the applicant under the {programme} route. 150 to 220 words. Structure: one-line subject; greeting; who the applicant is (degree, university, field) in two sentences; why this lab, naming one specific recent paper or topic from the context; the applicant's research idea in at most four sentences; the funding route and timeline; what is attached (CV, transcript, one-page plan); polite close. If writing in Japanese, use polite keigo appropriate for a first contact with a professor and put the subject line first; if the professor's name is given in Latin letters, address them as "<Surname> 先生" in Latin letters (for example "Hayashibe 先生") and do not convert the name to kanji or katakana.""",
    "research_plan": """Write a research plan (研究計画書 style) of about 800 words with these headings: Background and motivation; Research questions and objectives; Proposed methods; Expected results and significance; Timeline for the degree (by semester); Fit with the host lab (name the lab's topic). Base it on the applicant's research interests and the lab context. Mark any missing specifics as placeholders.""",
    "sop": """Write a statement of purpose of about 600 words: motivation rooted in a concrete experience; academic and work background with two specific achievements; why this programme and country; why this lab or department; goals after the degree, including contribution to {target}. First person, plain language, no cliches.""",
    "cv": """Produce an academic CV in Markdown with sections: Personal details (name, nationality, email placeholder); Education (reverse chronological, with GPA where given); Research experience; Publications and presentations; Work experience; Skills and languages (with test scores where given); Awards; References (two placeholders). Keep it to what fits on two pages. If writing in Japanese, follow the 履歴書 ordering and add a 志望動機 section.""",
}


def load_profile(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _context(profile: dict, opportunity: dict | None, professor: dict | None) -> str:
    parts = [
        "Applicant profile:",
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
    ]
    if opportunity:
        keys = (
            "title",
            "canonical_name",
            "provider",
            "host_country",
            "degree_levels",
            "funding_type",
            "deadline",
            "eligibility_summary",
            "required_documents",
            "language_requirements",
            "application_route",
            "supervisor_required",
            "apply_url",
        )
        parts += [
            "Programme:",
            yaml.safe_dump(
                {k: opportunity.get(k) for k in keys if opportunity.get(k)},
                allow_unicode=True,
                sort_keys=False,
            ),
        ]
    if professor:
        parts += [
            "Prospective supervisor / lab:",
            yaml.safe_dump(professor, allow_unicode=True, sort_keys=False),
        ]
    return "\n".join(parts)


def draft(
    client: LlmClient,
    kind: str,
    profile: dict,
    opportunity: dict | None,
    professor: dict | None,
    language: str,
    target: str,
    today: date,
) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    language_name = LANGUAGE_NAMES.get(language, language)
    programme = (
        (opportunity or {}).get("canonical_name")
        or (opportunity or {}).get("title")
        or "the scholarship"
    )
    professor_name = (professor or {}).get("name") or "[ADD: professor's name]"
    system = SYSTEM.format(target=target, language=language_name)
    user = f"Today: {today.isoformat()}\n\n{_context(profile, opportunity, professor)}\n\nTask:\n{INSTRUCTIONS[kind].format(professor=professor_name, programme=programme, target=target)}"
    completion = client.complete_text(
        system, user, max_tokens=2200 if kind != "email" else 700
    )
    if completion.error or not completion.raw.strip():
        raise RuntimeError(f"draft failed: {completion.error or 'empty response'}")
    text = completion.raw.strip() + "\n"
    return (
        flag_altered_name(text, professor_name)
        if professor and professor.get("name")
        else text
    )


def flag_altered_name(text: str, professor_name: str) -> str:
    surname = professor_name.split()[-1] if professor_name else ""
    if surname and surname.isascii() and surname.casefold() not in text.casefold():
        return f"[CHECK: the professor's name '{professor_name}' does not appear as given; verify the spelling before sending]\n\n{text}"
    return text


def write_draft(
    out_dir: Path, kind: str, label: str, language: str, content: str
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:40] or "draft"
    path = out_dir / f"{kind}-{slug}-{language}.md"
    path.write_text(content, encoding="utf-8")
    return path

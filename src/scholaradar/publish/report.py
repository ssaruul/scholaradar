from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

VERDICT_LABEL = {"yes": "Eligible", "no": "Not eligible", "unclear": "Unclear"}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _row(item: dict) -> str:
    link = item["apply_url"] or item["page_url"]
    title = _cell(item["title"])[:90]
    levels = ", ".join(item["degree_levels"]) or ""
    verdict = VERDICT_LABEL.get(item["target_eligible"], item["target_eligible"])
    if not item["evidence_verified"]:
        verdict += " (unverified)"
    return f"| {item['deadline'] or ''} | [{title}]({link}) | {_cell(item['host_country'])} | {_cell(levels)} | {_cell(item['funding_type'])} | {verdict} |"


def _table(items: list[dict]) -> str:
    if not items:
        return "_None._\n"
    header = "| Deadline | Opportunity | Host country | Level | Funding | Verdict |\n|---|---|---|---|---|---|\n"
    return header + "\n".join(_row(item) for item in items) + "\n"


def _changes_table(changes: list[dict]) -> str:
    if not changes:
        return "_None._\n"
    header = "| Opportunity | What changed | Before | After |\n|---|---|---|---|\n"
    body = "\n".join(
        f"| [{_cell(c['title'])[:80]}]({c['apply_url'] or c['page_url']}) | {_cell(c['field'])} | {_cell(c['old_value'])} | {_cell(c['new_value'])} |" for c in changes
    )
    return header + body + "\n"


FUNDING_LABEL = {"full": "fully funded", "partial": "partially funded", "tuition_only": "tuition only", "stipend_only": "stipend only", "unknown": "funding not stated"}


def render_report(rows: list[dict], new_rows: list[dict], target_name: str, today: date, pages_url: str, window_days: int = 30, changes: list[dict] | None = None, funding: list[str] | None = None) -> str:
    cutoff = today.isoformat()
    horizon = (today + timedelta(days=window_days)).isoformat()
    upcoming = [r for r in rows if r["deadline"] and cutoff <= r["deadline"] <= horizon and r["target_eligible"] != "no"]
    upcoming.sort(key=lambda r: r["deadline"])
    new_visible = [r for r in new_rows if r["target_eligible"] != "no" and (not r["deadline"] or r["deadline"] >= cutoff)]
    new_visible.sort(key=lambda r: (r["deadline"] or "9999", r["title"]))
    verdicts = Counter(r["target_eligible"] for r in rows)
    languages = Counter(r["lang"] for r in rows)
    countries = Counter(r["host_country"] for r in rows if r["host_country"])
    lines = [
        f"# Scholaradar report, {today.isoformat()}",
        "",
        f"{len(rows)} {' / '.join(FUNDING_LABEL.get(f, f) for f in funding) + ' ' if funding else ''}opportunities tracked for citizens of {target_name}: {verdicts.get('yes', 0)} eligible, {verdicts.get('unclear', 0)} unclear, {verdicts.get('no', 0)} not eligible.",
        f"Filterable dashboard: [{pages_url}]({pages_url}) (also `docs/index.html` in this repository). Full data: `docs/opportunities.csv`.",
        "",
        f"## New since the previous run ({len(new_visible)})",
        "",
        _table(new_visible),
        f"## Deadlines in the next {window_days} days ({len(upcoming)})",
        "",
        _table(upcoming),
        f"## Changed since the previous run ({len(changes or [])})",
        "",
        _changes_table(changes or []),
        "## Coverage",
        "",
        "Pages by language: " + ", ".join(f"{lang} {count}" for lang, count in languages.most_common()) + ".",
        "",
        "Top host countries: " + ", ".join(f"{country} {count}" for country, count in countries.most_common(10)) + ".",
        "",
        "Verdicts come from a local language model and are checked against a verbatim quote from the page; `unverified` means no supporting quote was found. Always confirm eligibility and deadlines on the official page before applying.",
        "",
    ]
    return "\n".join(lines)


def write_report(reports_dir: Path, content: str, today: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    dated = reports_dir / f"{today.isoformat()}.md"
    dated.write_text(content, encoding="utf-8")
    (reports_dir / "latest.md").write_text(content, encoding="utf-8")
    index_lines = ["# Reports", "", "Newest first. `latest.md` always mirrors the most recent run.", ""]
    for path in sorted(reports_dir.glob("20??-??-??.md"), reverse=True):
        index_lines.append(f"- [{path.stem}]({path.name})")
    (reports_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return dated

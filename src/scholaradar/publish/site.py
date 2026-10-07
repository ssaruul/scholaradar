from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def write_badges(site_dir: Path, shown: int, eligible: int, today: date, funding_label: str) -> None:
    badges = site_dir / "badges"
    badges.mkdir(parents=True, exist_ok=True)
    (badges / "opportunities.json").write_text(json.dumps({"schemaVersion": 1, "label": funding_label, "message": f"{shown} tracked, {eligible} eligible", "color": "2456b5"}), encoding="utf-8")
    (badges / "updated.json").write_text(json.dumps({"schemaVersion": 1, "label": "last run", "message": today.isoformat(), "color": "1b7f3b"}), encoding="utf-8")

SITE_FIELDS = (
    "id", "title", "provider", "host_country", "degree_levels", "fields_of_study", "funding_type", "deadline", "deadline_text",
    "target_eligible", "evidence_verified", "nationality_mode", "eligibility_summary", "evidence_quote", "apply_url", "page_url",
    "lang", "first_seen", "also_on",
)


def write_site(site_dir: Path, templates_dir: Path, rows: list[dict], target_name: str, today: date, repo_url: str = "https://github.com/ssaruul/scholaradar", funding: list[str] | None = None) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    items = [{key: row.get(key, []) for key in SITE_FIELDS} for row in rows]
    data_json = json.dumps(items, ensure_ascii=False)
    (site_dir / "data.json").write_text(data_json, encoding="utf-8")
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
    template = env.get_template("site.html.j2")
    html = template.render(
        data_json=data_json.replace("</", "<\\/"),
        target_name=target_name,
        repo_url=repo_url,
        default_funding=list(funding or []),
        generated=today.isoformat(),
        total=len(items),
        eligible=sum(1 for item in items if item["target_eligible"] == "yes"),
    )
    index = site_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    return index

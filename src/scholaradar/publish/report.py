from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

STRINGS = {
    "en": {
        "title": "Scholaradar report, {today}",
        "intro": "{n} {funding}opportunities tracked for citizens of {target}: {yes} eligible, {unclear} unclear, {no} not eligible.",
        "links": "Filterable dashboard: [{url}]({url}) (also `docs/index.html` in this repository). Calendar: `deadlines.ics`. Full data: `docs/opportunities.csv`.",
        "new": "New since the previous run ({n})",
        "upcoming": "Deadlines in the next {days} days ({n})",
        "open": "All open opportunities ({n})",
        "open_note": "Eligible or unclear, fully funded, sorted by deadline; opportunities without a stated deadline are listed last.",
        "changed": "Changed since the previous run ({n})",
        "coverage": "Coverage",
        "by_language": "Pages by language",
        "top_hosts": "Top host countries",
        "footer": "Verdicts come from a local language model and are checked against a verbatim quote from the page; `unverified` means no supporting quote was found. Always confirm eligibility and deadlines on the official page before applying.",
        "none": "_None._",
        "headers": ("Deadline", "Days left", "Opportunity", "Host country", "Level", "Funding", "Verdict"),
        "change_headers": ("Opportunity", "What changed", "Before", "After"),
        "verdict": {"yes": "Eligible", "no": "Not eligible", "unclear": "Unclear"},
        "unverified": " (unverified)",
        "today": "today", "tomorrow": "tomorrow", "days": "{n}", "no_deadline": "not stated", "more": "... and {n} more on the dashboard.",
        "funding": {"full": "fully funded ", "partial": "partially funded ", "stipend_only": "stipend-only ", "tuition_only": "tuition-only ", "unknown": ""},
        "levels": {"bachelor": "bachelor", "master": "master", "phd": "PhD", "postdoc": "postdoc", "research": "research", "exchange": "exchange", "short_course": "short course", "language": "language", "other": "other"},
        "funding_cell": {"full": "full", "partial": "partial", "tuition_only": "tuition only", "stipend_only": "stipend only", "unknown": "unknown"},
    },
    "mn": {
        "title": "Scholaradar тайлан, {today}",
        "intro": "Монгол Улсын иргэдэд зориулсан {n} {funding}тэтгэлэг бүртгэлтэй: {yes} хамаарна, {unclear} тодорхойгүй, {no} хамаарахгүй.",
        "links": "Шүүлтүүртэй самбар: [{url}]({url}) (энэ репо дотор `docs/index.html`). Календарь: `deadlines.ics`. Бүх өгөгдөл: `docs/opportunities.csv`.",
        "new": "Өмнөх ажиллагаанаас хойш шинээр нэмэгдсэн ({n})",
        "upcoming": "Ойрын {days} хоногт дуусах хугацаатай ({n})",
        "open": "Одоо нээлттэй бүх тэтгэлэг ({n})",
        "open_note": "Хамаарах эсвэл тодорхойгүй, бүрэн санхүүжилттэй, хугацаагаар эрэмбэлсэн; хугацаа заагаагүй тэтгэлгүүд хамгийн сүүлд.",
        "changed": "Өмнөх ажиллагаанаас хойш өөрчлөгдсөн ({n})",
        "coverage": "Хамрах хүрээ",
        "by_language": "Хуудсууд хэлээр",
        "top_hosts": "Суралцах улсууд",
        "footer": "Дүгнэлтийг локал хэлний загвар гаргаж, хуудасны үгчилсэн ишлэлээр шалгасан; `баталгаажаагүй` гэдэг нь нотлох өгүүлбэр олдоогүй гэсэн үг. Өргөдөл гаргахын өмнө албан ёсны хуудаснаас хамаарах эсэх, хугацааг заавал баталгаажуулна уу.",
        "none": "_Байхгүй._",
        "headers": ("Хугацаа", "Үлдсэн хоног", "Тэтгэлэг", "Суралцах улс", "Түвшин", "Санхүүжилт", "Хамаарах эсэх"),
        "change_headers": ("Тэтгэлэг", "Юу өөрчлөгдсөн", "Өмнө", "Дараа"),
        "verdict": {"yes": "Хамаарна", "no": "Хамаарахгүй", "unclear": "Тодорхойгүй"},
        "unverified": " (баталгаажаагүй)",
        "today": "өнөөдөр", "tomorrow": "маргааш", "days": "{n}", "no_deadline": "заагаагүй", "more": "... мөн {n} тэтгэлэг самбар дээр.",
        "funding": {"full": "бүрэн санхүүжилттэй ", "partial": "хэсэгчилсэн санхүүжилттэй ", "stipend_only": "зөвхөн тэтгэмжтэй ", "tuition_only": "зөвхөн төлбөртэй ", "unknown": ""},
        "levels": {"bachelor": "бакалавр", "master": "магистр", "phd": "доктор", "postdoc": "постдок", "research": "судалгаа", "exchange": "солилцоо", "short_course": "богино хугацааны", "language": "хэлний", "other": "бусад"},
        "funding_cell": {"full": "бүрэн", "partial": "хэсэгчилсэн", "tuition_only": "зөвхөн төлбөр", "stipend_only": "зөвхөн тэтгэмж", "unknown": "тодорхойгүй"},
    },
}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _days_left(deadline: str | None, today: date, s: dict) -> str:
    if not deadline:
        return s["no_deadline"]
    delta = (date.fromisoformat(deadline) - today).days
    if delta == 0:
        return s["today"]
    if delta == 1:
        return s["tomorrow"]
    return s["days"].format(n=delta)


def _row(item: dict, today: date, s: dict) -> str:
    title = _cell(item["title"])[:90]
    levels = ", ".join(s["levels"].get(level, level) for level in item["degree_levels"])
    verdict = s["verdict"].get(item["target_eligible"], item["target_eligible"])
    if not item["evidence_verified"]:
        verdict += s["unverified"]
    apply_link = f" ([apply]({item['apply_url']}))" if item["apply_url"] and item["apply_url"] != item["page_url"] else ""
    return (
        f"| {item['deadline'] or ''} | {_days_left(item['deadline'], today, s)} | [{title}]({item['page_url']}){apply_link} | "
        f"{_cell(item['host_country'])} | {_cell(levels)} | {s['funding_cell'].get(item['funding_type'], item['funding_type'])} | {verdict} |"
    )


def _table(items: list[dict], today: date, s: dict, limit: int | None = None) -> str:
    if not items:
        return s["none"] + "\n"
    header = "| " + " | ".join(s["headers"]) + " |\n|" + "---|" * len(s["headers"]) + "\n"
    shown = items[:limit] if limit else items
    body = header + "\n".join(_row(item, today, s) for item in shown) + "\n"
    if limit and len(items) > limit:
        body += "\n" + s["more"].format(n=len(items) - limit) + "\n"
    return body


def _changes_table(changes: list[dict], s: dict) -> str:
    if not changes:
        return s["none"] + "\n"
    header = "| " + " | ".join(s["change_headers"]) + " |\n|---|---|---|---|\n"
    body = "\n".join(
        f"| [{_cell(c['title'])[:80]}]({c['page_url'] or c['apply_url']}) | {_cell(c['field'])} | {_cell(c['old_value'])} | {_cell(c['new_value'])} |" for c in changes
    )
    return header + body + "\n"


def render_report(
    rows: list[dict], new_rows: list[dict], target_name: str, today: date, pages_url: str, window_days: int = 90,
    changes: list[dict] | None = None, funding: list[str] | None = None, language: str = "en", max_open: int = 80,
) -> str:
    s = STRINGS.get(language, STRINGS["en"])
    cutoff = today.isoformat()
    horizon = (today + timedelta(days=window_days)).isoformat()
    open_rows = [r for r in rows if r["target_eligible"] != "no" and (not r["deadline"] or r["deadline"] >= cutoff)]
    open_rows.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or "", r["title"]))
    upcoming = [r for r in open_rows if r["deadline"] and r["deadline"] <= horizon]
    new_visible = [r for r in new_rows if r["target_eligible"] != "no" and (not r["deadline"] or r["deadline"] >= cutoff)]
    new_visible.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or "", r["title"]))
    verdicts = Counter(r["target_eligible"] for r in rows)
    languages = Counter(r["lang"] for r in rows)
    countries = Counter(r["host_country"] for r in rows if r["host_country"])
    funding_label = "".join(s["funding"].get(f, "") for f in (funding or []))
    lines = [
        "# " + s["title"].format(today=today.isoformat()),
        "",
        s["intro"].format(n=len(rows), funding=funding_label, target=target_name, yes=verdicts.get("yes", 0), unclear=verdicts.get("unclear", 0), no=verdicts.get("no", 0)),
        s["links"].format(url=pages_url),
        "",
        "## " + s["new"].format(n=len(new_visible)),
        "",
        _table(new_visible, today, s),
        "## " + s["upcoming"].format(days=window_days, n=len(upcoming)),
        "",
        _table(upcoming, today, s),
        "## " + s["open"].format(n=len(open_rows)),
        "",
        s["open_note"],
        "",
        _table(open_rows, today, s, max_open),
        "## " + s["changed"].format(n=len(changes or [])),
        "",
        _changes_table(changes or [], s),
        "## " + s["coverage"],
        "",
        s["by_language"] + ": " + ", ".join(f"{lang} {count}" for lang, count in languages.most_common()) + ".",
        "",
        s["top_hosts"] + ": " + ", ".join(f"{country} {count}" for country, count in countries.most_common(10)) + ".",
        "",
        s["footer"],
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

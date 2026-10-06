from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

VERDICT_LABEL = {"yes": "Eligible", "no": "Not eligible", "unclear": "Unclear"}


def _rfc822(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.strftime("%a, %d %b %Y %H:%M:%S %z")


def _guid(row: dict) -> str:
    return hashlib.sha1((row["apply_url"] or row["page_url"]).encode()).hexdigest()


def write_rss(path: Path, rows: list[dict], target_name: str, site_url: str, today: date, limit: int = 100) -> Path:
    cutoff = today.isoformat()
    items = [r for r in rows if r["target_eligible"] != "no" and (not r["deadline"] or r["deadline"] >= cutoff)]
    items.sort(key=lambda r: r["first_seen"], reverse=True)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>Scholaradar: scholarships for citizens of {escape(target_name)}</title>",
        f"<link>{escape(site_url or 'https://github.com/ssaruul/scholaradar')}</link>",
        f"<description>New scholarships and fellowships open to citizens of {escape(target_name)}, with deadlines.</description>",
        "<language>en</language>",
        f"<lastBuildDate>{_rfc822(datetime.now(timezone.utc).isoformat())}</lastBuildDate>",
    ]
    if site_url:
        parts.append(f'<atom:link href="{escape(site_url.rstrip("/") + "/feed.xml")}" rel="self" type="application/rss+xml"/>')
    for row in items[:limit]:
        verdict = VERDICT_LABEL.get(row["target_eligible"], row["target_eligible"])
        deadline = f"Deadline {row['deadline']}. " if row["deadline"] else ""
        meta = ", ".join(part for part in (row["host_country"], ", ".join(row["degree_levels"]), row["funding_type"]) if part)
        description = f"{verdict}. {deadline}{meta}. {row['eligibility_summary'] or ''}"
        if row["evidence_quote"]:
            description += f" Evidence: \u201c{row['evidence_quote'][:300]}\u201d"
        parts += [
            "<item>",
            f"<title>{escape(row['title'][:150])}</title>",
            f"<link>{escape(row['apply_url'] or row['page_url'])}</link>",
            f'<guid isPermaLink="false">{_guid(row)}</guid>',
            f"<pubDate>{_rfc822(row['first_seen'])}</pubDate>",
            f"<description>{escape(description)}</description>",
            "</item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= 72:
        return line
    chunks = []
    current = b""
    for char in line:
        piece = char.encode("utf-8")
        if len(current) + len(piece) > 72:
            chunks.append(current.decode("utf-8"))
            current = b" " + piece
        else:
            current += piece
    chunks.append(current.decode("utf-8"))
    return "\r\n".join(chunks)


def write_ics(path: Path, rows: list[dict], target_name: str, today: date, horizon_days: int = 365) -> Path:
    cutoff = today.isoformat()
    horizon = (today + timedelta(days=horizon_days)).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Scholaradar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Scholarship deadlines ({target_name})",
    ]
    for row in rows:
        if not row["deadline"] or row["target_eligible"] == "no" or not (cutoff <= row["deadline"] <= horizon):
            continue
        day = date.fromisoformat(row["deadline"])
        verdict = VERDICT_LABEL.get(row["target_eligible"], row["target_eligible"])
        summary = f"Deadline: {row['title'][:80]}"
        description = f"{verdict}. {row['host_country'] or ''} {', '.join(row['degree_levels'])}. {row['eligibility_summary'] or ''} {row['apply_url'] or row['page_url']}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_guid(row)}@scholaradar",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description.strip())}",
            f"URL:{row['apply_url'] or row['page_url']}",
            "BEGIN:VALARM",
            "TRIGGER:-P7D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape('One week left: ' + row['title'][:80])}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(_fold(line) for line in lines) + "\r\n", encoding="utf-8")
    return path

from __future__ import annotations

from datetime import date, datetime, timedelta

FOLLOW_UP_DAYS = 10
STATUSES = ("planned", "sent", "replied", "accepted", "declined")


def follow_up_due(row: dict, today: date) -> bool:
    if row["status"] != "sent" or not row["sent_at"]:
        return False
    sent = datetime.fromisoformat(row["sent_at"]).date()
    return today - sent >= timedelta(days=FOLLOW_UP_DAYS)


def render_outreach(rows: list[dict], today: date, language: str = "en") -> str:
    if not rows:
        return "_None._\n" if language != "mn" else "_Байхгүй._\n"
    headers = (
        (
            "ID",
            "Professor",
            "University",
            "Status",
            "Sent",
            "Replied",
            "Follow-up",
            "Note",
        )
        if language != "mn"
        else (
            "ID",
            "Профессор",
            "Их сургууль",
            "Төлөв",
            "Илгээсэн",
            "Хариу",
            "Дахин холбогдох",
            "Тэмдэглэл",
        )
    )
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        due = (
            ("DUE" if language != "mn" else "ХЭРЭГТЭЙ")
            if follow_up_due(row, today)
            else ""
        )
        lines.append(
            f"| {row['id']} | {row['professor']} | {row['university'] or ''} | {row['status']} | {(row['sent_at'] or '')[:10]} | {(row['replied_at'] or '')[:10]} | {due} | {(row['note'] or '').replace('|', '/')[:60]} |"
        )
    return "\n".join(lines) + "\n"

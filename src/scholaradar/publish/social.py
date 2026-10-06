from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

log = logging.getLogger(__name__)

STRINGS = {
    "en": {
        "title": "New scholarships for citizens of {target}, {today}",
        "deadline": "deadline {deadline}",
        "no_deadline": "no deadline stated",
        "more": "and {n} more on the dashboard",
        "dashboard": "All opportunities with filters: {url}",
        "footer": "Eligibility is checked against the official page text. Confirm on the official site before applying.",
    },
    "mn": {
        "title": "{target} улсын иргэдэд нээлттэй шинэ тэтгэлэгүүд, {today}",
        "deadline": "хугацаа {deadline}",
        "no_deadline": "хугацаа заагаагүй",
        "more": "мөн {n} тэтгэлэг самбар дээр",
        "dashboard": "Бүх тэтгэлэг, шүүлтүүртэй: {url}",
        "footer": "Албан ёсны хуудасны текстээр шалгасан. Өргөдөл гаргахын өмнө албан ёсны сайтаас баталгаажуулна уу.",
    },
}

TARGET_NAMES_MN = {"Mongolia": "Монгол"}


def format_digest(rows: list[dict], target: str, today: date, pages_url: str, max_items: int, lang: str = "en") -> tuple[str, list[int]]:
    strings = STRINGS.get(lang, STRINGS["en"])
    target_name = TARGET_NAMES_MN.get(target, target) if lang == "mn" else target
    shown = rows[:max_items]
    lines = [strings["title"].format(target=target_name, today=today.isoformat()), ""]
    for row in shown:
        deadline = strings["deadline"].format(deadline=row["deadline"]) if row["deadline"] else strings["no_deadline"]
        where = f", {row['host_country']}" if row["host_country"] else ""
        levels = f" ({', '.join(row['degree_levels'])})" if row["degree_levels"] else ""
        lines.append(f"• {row['title'][:110]}{where}{levels}, {deadline}")
        lines.append(f"  {row['apply_url'] or row['page_url']}")
    if len(rows) > len(shown):
        lines.append("")
        lines.append(strings["more"].format(n=len(rows) - len(shown)))
    if pages_url:
        lines.append("")
        lines.append(strings["dashboard"].format(url=pages_url))
    lines.append("")
    lines.append(strings["footer"])
    return "\n".join(lines), [row["id"] for row in shown]


@dataclass(frozen=True)
class PostResult:
    ok: bool
    external_id: str | None
    error: str | None = None


@dataclass(frozen=True)
class FacebookPage:
    page_id: str
    token: str
    graph_version: str = "v23.0"

    def post(self, message: str, link: str | None = None) -> PostResult:
        payload = {"message": message, "access_token": self.token}
        if link:
            payload["link"] = link
        try:
            response = httpx.post(f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/feed", data=payload, timeout=30)
        except httpx.HTTPError as exc:
            return PostResult(False, None, f"http_error:{type(exc).__name__}")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code != 200:
            return PostResult(False, None, str(body.get("error", {}).get("message") or response.text[:200]))
        return PostResult(True, body.get("id"))


@dataclass(frozen=True)
class TelegramChannel:
    bot_token: str
    chat_id: str

    def post(self, message: str, link: str | None = None) -> PostResult:
        payload = {"chat_id": self.chat_id, "text": message[:4000], "disable_web_page_preview": True}
        try:
            response = httpx.post(f"https://api.telegram.org/bot{self.bot_token}/sendMessage", json=payload, timeout=30)
        except httpx.HTTPError as exc:
            return PostResult(False, None, f"http_error:{type(exc).__name__}")
        body = response.json()
        if not body.get("ok"):
            return PostResult(False, None, str(body.get("description") or response.text[:200]))
        return PostResult(True, str(body["result"]["message_id"]))

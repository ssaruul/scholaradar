from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .publish.feeds import _fold, _ics_escape

STEPS = {
    "en": [
        (-150, "Shortlist 8 to 10 professors and read two recent papers from each lab"),
        (
            -120,
            "Email prospective supervisors with CV, transcript and a one-page research idea",
        ),
        (-110, "Book the TOEFL iBT or IELTS test date (results take about two weeks)"),
        (
            -90,
            "Ask two referees for recommendation letters; give them your CV and the programme page",
        ),
        (
            -75,
            "Order official transcripts and the graduation certificate from your university",
        ),
        (
            -60,
            "Translate documents into English or Japanese and notarise them in Ulaanbaatar",
        ),
        (-50, "Apostille the notarised documents at the Ministry of Foreign Affairs"),
        (-45, "Research plan: first full draft"),
        (
            -30,
            "Research plan final; statement of purpose; CV in the programme's format",
        ),
        (
            -21,
            "Obtain the supervisor's letter of acceptance (informal is enough for MEXT embassy route)",
        ),
        (
            -14,
            "Medical certificate on the official form; passport photos; passport copy",
        ),
        (-7, "Submit the application and keep PDF copies of everything"),
        (0, "Deadline"),
    ],
    "mn": [
        (-150, "8-10 профессор сонгож, лаборатори бүрийн сүүлийн 2 өгүүллийг унших"),
        (
            -120,
            "Удирдагч багш нарт CV, дүнгийн хуудас, нэг хуудас судалгааны санаа хавсаргаж имэйл илгээх",
        ),
        (-110, "TOEFL iBT эсвэл IELTS шалгалтын огноо захиалах (хариу ~2 долоо хоног)"),
        (-90, "Хоёр тодорхойлогчоос захидал хүсэх; CV болон хөтөлбөрийн хуудсыг өгөх"),
        (-75, "Дүнгийн албан ёсны хуудас, төгсөлтийн гэрчилгээг сургуулиасаа захиалах"),
        (
            -60,
            "Бичиг баримтаа англи/япон хэл рүү орчуулж, Улаанбаатарт нотариатаар баталгаажуулах",
        ),
        (-50, "Гадаад хэргийн яаманд апостиль хийлгэх"),
        (-45, "Судалгааны төлөвлөгөө: бүрэн эхний хувилбар"),
        (
            -30,
            "Судалгааны төлөвлөгөө эцсийн хувилбар; зорилгын эссэ; хөтөлбөрийн форматаар CV",
        ),
        (
            -21,
            "Удирдагч багшийн зөвшөөрлийн захидал авах (MEXT элчингийн замд албан бус байж болно)",
        ),
        (
            -14,
            "Албан ёсны маягтаар эрүүл мэндийн тодорхойлолт; цээж зураг; паспортын хуулбар",
        ),
        (-7, "Өргөдлөө илгээж, бүх баримтын PDF хуулбарыг хадгалах"),
        (0, "Хугацаа дуусна"),
    ],
}
ROUTE_STEPS = {
    "embassy": {
        "en": (
            -100,
            "Check the embassy's own application window; embassy deadlines are often earlier than the programme's",
        ),
        "mn": (
            -100,
            "Элчин сайдын яамны бүртгэлийн хугацааг шалгах; ихэвчлэн хөтөлбөрийнхөөс эрт байдаг",
        ),
    },
    "university": {
        "en": (
            -100,
            "Check the graduate school's admission guide for the exact document formats",
        ),
        "mn": (-100, "Их сургуулийн элсэлтийн зааврыг уншиж баримтын форматыг шалгах"),
    },
}
DOC_STEP = {"en": "Prepare: {doc}", "mn": "Бэлтгэх: {doc}"}


@dataclass(frozen=True)
class PlanItem:
    day: date
    task: str
    offset: int


def build_plan(
    deadline: date,
    language: str = "en",
    route: str = "unclear",
    required_documents: list[str] | None = None,
    today: date | None = None,
) -> list[PlanItem]:
    lang = language if language in STEPS else "en"
    today = today or date.today()
    items = [
        PlanItem(deadline + timedelta(days=offset), task, offset)
        for offset, task in STEPS[lang]
    ]
    if route in ROUTE_STEPS:
        offset, task = ROUTE_STEPS[route][lang]
        items.append(PlanItem(deadline + timedelta(days=offset), task, offset))
    for doc in required_documents or []:
        items.append(
            PlanItem(
                deadline + timedelta(days=-40), DOC_STEP[lang].format(doc=doc), -40
            )
        )
    items.sort(key=lambda item: (item.day, item.offset))
    overdue = [item for item in items if item.day < today and item.offset != 0]
    if overdue:
        catch_up = PlanItem(
            today,
            (
                "Catch up on overdue steps: "
                if lang == "en"
                else "Хоцорсон алхмуудыг нөхөх: "
            )
            + "; ".join(item.task for item in overdue),
            0,
        )
        items = [catch_up] + [item for item in items if item.day >= today]
    return items


def render_plan(
    title: str,
    deadline: date,
    items: list[PlanItem],
    language: str = "en",
    url: str = "",
) -> str:
    heading = "Application plan" if language != "mn" else "Өргөдлийн төлөвлөгөө"
    lines = [
        f"# {heading}: {title}",
        "",
        f"{'Deadline' if language != 'mn' else 'Хугацаа'}: {deadline.isoformat()}"
        + (f" · {url}" if url else ""),
        "",
        "| "
        + (
            "Date | Days before deadline | Task"
            if language != "mn"
            else "Огноо | Хугацаанаас өмнө | Ажил"
        )
        + " |",
        "|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {item.day.isoformat()} | {abs(item.offset) if item.offset else 0} | {item.task} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_plan_ics(path: Path, title: str, items: list[PlanItem]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Scholaradar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape('Plan: ' + title[:60])}",
    ]
    for index, item in enumerate(items):
        lines += [
            "BEGIN:VEVENT",
            f"UID:plan-{stamp}-{index}@scholaradar",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{item.day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(item.day + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(item.task[:100])}",
            f"DESCRIPTION:{_ics_escape(title)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\r\n".join(_fold(line) for line in lines) + "\r\n", encoding="utf-8"
    )
    return path


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:50] or "plan"

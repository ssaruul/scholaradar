from __future__ import annotations

import io
import re
from dataclasses import dataclass

import trafilatura
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MONGOLIAN_LETTERS = re.compile(r"[өүӨҮ]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
HIRAGANA_KATAKANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-z]")
TURKISH = re.compile(r"[ğışĞİŞ]")
GERMAN_HINTS = re.compile(r"\b(und|für|nicht|Stipendium|Bewerbung|Studierende)\b")


@dataclass(frozen=True)
class Extracted:
    text: str
    title: str
    date: str | None
    lang: str


def guess_language(text: str) -> str:
    sample = text[:4000]
    if HANGUL.search(sample):
        return "ko"
    if HIRAGANA_KATAKANA.search(sample):
        return "ja"
    cjk = len(CJK.findall(sample))
    cyr = len(CYRILLIC.findall(sample))
    lat = len(LATIN.findall(sample))
    if cjk > max(cyr, lat) * 0.5 and cjk > 20:
        return "zh"
    if cyr > lat:
        return "mn" if len(MONGOLIAN_LETTERS.findall(sample)) > 3 else "ru"
    if len(TURKISH.findall(sample)) > 10:
        return "tr"
    if len(GERMAN_HINTS.findall(sample)) > 8:
        return "de"
    return "en"


def extract_html(html: bytes, url: str) -> Extracted | None:
    doc = trafilatura.bare_extraction(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        include_links=False,
        favor_recall=True,
        with_metadata=True,
    )
    if doc is None or not doc.text or len(doc.text.strip()) < 80:
        return None
    text = doc.text.strip()
    return Extracted(text=text, title=(doc.title or "").strip(), date=doc.date, lang=guess_language(text))


def extract_pdf(data: bytes) -> Extracted | None:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:40]]
        metadata_title = reader.metadata.title if reader.metadata and reader.metadata.title else ""
    except (PdfReadError, ValueError, KeyError, TypeError):
        return None
    text = re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()
    if len(text) < 80:
        return None
    title = metadata_title or text.splitlines()[0][:200]
    return Extracted(text=text, title=title.strip(), date=None, lang=guess_language(text))

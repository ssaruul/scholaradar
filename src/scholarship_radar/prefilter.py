from __future__ import annotations

import re


def keyword_hit(text: str, keywords: list[str]) -> str | None:
    folded = text.casefold()
    for keyword in keywords:
        if keyword.casefold() in folded:
            return keyword
    return None


def nationality_hits(text: str, names: list[str]) -> list[str]:
    folded = text.casefold()
    return [name for name in names if name.casefold() in folded]


SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")


def sentences_mentioning(text: str, names: list[str]) -> list[str]:
    folded_names = [name.casefold() for name in names]
    found = []
    for sentence in SENTENCE_SPLIT.split(text):
        folded = sentence.casefold()
        if any(name in folded for name in folded_names):
            found.append(sentence.strip())
    return found

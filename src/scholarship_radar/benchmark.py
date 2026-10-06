from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import yaml

from .config import Settings
from .db import PageRow
from .fetch import Fetcher
from .llm.client import LlmClient
from .llm.extract import extract_one
from .llm.schema import opportunity_json_schema
from .textract import extract_html, extract_pdf

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Case:
    url: str
    target_eligible: str
    deadline: str | None
    is_opportunity: bool
    note: str


@dataclass
class CaseResult:
    url: str
    expected_eligible: str
    predicted_eligible: str | None
    expected_deadline: str | None
    predicted_deadline: str | None
    expected_is_opportunity: bool
    predicted_is_opportunity: bool | None
    verified: bool
    error: str | None
    seconds: float
    prompt_tokens: int
    completion_tokens: int


def load_cases(path: Path) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = []
    for item in raw.get("cases", []):
        deadline = item.get("deadline")
        cases.append(
            Case(
                url=item["url"],
                target_eligible=str(item["target_eligible"]),
                deadline=str(deadline) if deadline else None,
                is_opportunity=bool(item.get("is_opportunity", True)),
                note=item.get("note", ""),
            )
        )
    return cases


def _cached_text(settings: Settings, fetcher: Fetcher, url: str) -> tuple[str, str] | None:
    cache_dir = settings.data_dir / "benchmark" / "text"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        payload = json.loads(cached.read_text(encoding="utf-8"))
        return payload["title"], payload["text"]
    result = fetcher.fetch(url)
    if not result.ok:
        log.warning("benchmark fetch failed %s: %s %s", url, result.status, result.error)
        return None
    extracted = extract_pdf(result.body) if result.is_pdf else extract_html(result.body, result.final_url)
    if extracted is None:
        log.warning("benchmark no text %s", url)
        return None
    cached.write_text(json.dumps({"title": extracted.title, "text": extracted.text}, ensure_ascii=False), encoding="utf-8")
    return extracted.title, extracted.text


def run_benchmark(settings: Settings, model: str, labels_path: Path, limit: int) -> int:
    cases = load_cases(labels_path if labels_path.is_absolute() else settings.root_dir / labels_path)
    if limit:
        cases = cases[:limit]
    fetcher = Fetcher(settings.fetch)
    texts: dict[str, tuple[str, str]] = {}
    for case in cases:
        cached = _cached_text(settings, fetcher, case.url)
        if cached:
            texts[case.url] = cached
    fetcher.close()
    client = LlmClient(settings.llm, model=model)
    if not client.healthy():
        print(f"LLM endpoint not reachable at {settings.llm.base_url}")
        return 2
    schema = opportunity_json_schema()
    today = date.today()
    started = time.monotonic()

    def work(indexed: tuple[int, Case]) -> CaseResult:
        index, case = indexed
        if case.url not in texts:
            return CaseResult(case.url, case.target_eligible, None, case.deadline, None, case.is_opportunity, None, False, "fetch_failed", 0.0, 0, 0)
        title, text = texts[case.url]
        page = PageRow(index, case.url, case.url, None, "benchmark", None, title, None, [], "fetched", None, None)
        outcome = extract_one(client, settings, page, text, today, schema)
        opp = outcome.opportunity
        return CaseResult(
            url=case.url,
            expected_eligible=case.target_eligible,
            predicted_eligible=opp.target_eligible if opp else None,
            expected_deadline=case.deadline,
            predicted_deadline=opp.deadline if opp else None,
            expected_is_opportunity=case.is_opportunity,
            predicted_is_opportunity=opp.is_opportunity if opp else None,
            verified=outcome.verified,
            error=outcome.error,
            seconds=outcome.completion.seconds,
            prompt_tokens=outcome.completion.prompt_tokens,
            completion_tokens=outcome.completion.completion_tokens,
        )

    with ThreadPoolExecutor(max_workers=settings.llm.concurrency) as pool:
        results = list(pool.map(work, enumerate(cases, start=1)))
    wall = time.monotonic() - started
    client.close()
    scored = [r for r in results if r.error is None]
    opportunities = [r for r in scored if r.expected_is_opportunity]
    eligible_correct = sum(1 for r in opportunities if r.predicted_eligible == r.expected_eligible)
    deadline_cases = [r for r in opportunities if r.expected_deadline]
    deadline_correct = sum(1 for r in deadline_cases if r.predicted_deadline == r.expected_deadline)
    opp_correct = sum(1 for r in scored if r.predicted_is_opportunity == r.expected_is_opportunity)
    false_yes = sum(1 for r in opportunities if r.predicted_eligible == "yes" and r.expected_eligible != "yes")
    completion_tokens = sum(r.completion_tokens for r in results)
    summary = {
        "model": model,
        "cases": len(cases),
        "scored": len(scored),
        "errors": sorted({r.error for r in results if r.error}),
        "eligible_accuracy": round(eligible_correct / len(opportunities), 3) if opportunities else 0.0,
        "false_yes": false_yes,
        "deadline_accuracy": round(deadline_correct / len(deadline_cases), 3) if deadline_cases else None,
        "is_opportunity_accuracy": round(opp_correct / len(scored), 3) if scored else 0.0,
        "verified_rate": round(sum(1 for r in opportunities if r.verified) / len(opportunities), 3) if opportunities else 0.0,
        "wall_seconds": round(wall, 1),
        "gen_tokens_per_second": round(completion_tokens / wall, 1) if wall else 0.0,
        "prompt_tokens": sum(r.prompt_tokens for r in results),
        "completion_tokens": completion_tokens,
    }
    out_dir = settings.data_dir / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_model = model.replace("/", "_")
    (out_dir / f"{safe_model}.json").write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in results:
        flag = "ok " if r.predicted_eligible == r.expected_eligible else "BAD"
        print(f"{flag} {r.expected_eligible:>7} -> {str(r.predicted_eligible):>7}  dl {str(r.expected_deadline):>10} -> {str(r.predicted_deadline):>10}  {r.url}")
    return 0

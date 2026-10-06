from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import db
from .config import Settings, load_secrets, load_settings
from .fetch import Fetcher
from .llm.client import LlmClient
from .llm.extract import extract_pages
from .pipeline import discover, fetch_pages
from .publish.run import publish_all

log = logging.getLogger("scholarship_radar")


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve()


def cmd_init_db(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    from .pipeline import sync_sources

    sync_sources(conn, settings)
    print(f"database ready at {settings.db_path} with {len(settings.sources)} sources")
    return 0


def cmd_discover(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    run_id = db.start_run(conn)
    fetcher = Fetcher(settings.fetch)
    stats = discover(conn, settings, fetcher, run_id, date.today(), skip_search=args.skip_search)
    fetcher.close()
    db.finish_run(conn, run_id, asdict(stats))
    conn.commit()
    print(asdict(stats))
    return 0


def cmd_fetch(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    fetcher = Fetcher(settings.fetch)
    stats = fetch_pages(conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run)
    fetcher.close()
    print(asdict(stats))
    print(db.status_counts(conn))
    return 0


def cmd_extract(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    client = LlmClient(settings.llm, model=args.model)
    if not client.healthy():
        print(f"LLM endpoint not reachable at {settings.llm.base_url}", file=sys.stderr)
        return 2
    stats = extract_pages(conn, settings, client, args.limit or 10_000, date.today())
    client.close()
    print(asdict(stats))
    return 0


def cmd_publish(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    run_id = db.start_run(conn)
    stats = publish_all(conn, settings, load_secrets(settings.root_dir), run_id, date.today(), force_email=args.send_test)
    db.finish_run(conn, run_id, asdict(stats))
    conn.commit()
    print(asdict(stats))
    return 0


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    run_id = db.start_run(conn)
    today = date.today()
    fetcher = Fetcher(settings.fetch)
    discover_stats = discover(conn, settings, fetcher, run_id, today, skip_search=args.skip_search)
    log.info("discover: %s", asdict(discover_stats))
    fetch_stats = fetch_pages(conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run)
    log.info("fetch: %s", asdict(fetch_stats))
    if fetch_stats.links_added:
        link_stats = fetch_pages(conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run)
        log.info("fetch (followed links): %s", asdict(link_stats))
    fetcher.close()
    counts: dict[str, object] = {"discover": asdict(discover_stats), "fetch": asdict(fetch_stats)}
    if not args.skip_llm:
        client = LlmClient(settings.llm, model=args.model)
        if client.healthy():
            extract_stats = extract_pages(conn, settings, client, args.limit or 10_000, today)
            log.info("extract: %s", asdict(extract_stats))
            counts["extract"] = asdict(extract_stats)
        else:
            log.warning("LLM endpoint not reachable at %s, skipping extraction", settings.llm.base_url)
        client.close()
    publish_stats = publish_all(conn, settings, load_secrets(settings.root_dir), run_id, today)
    counts["publish"] = asdict(publish_stats)
    db.finish_run(conn, run_id, counts)
    conn.commit()
    print(counts)
    return 0


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    print("pages:", db.status_counts(conn))
    rows = db.opportunities(conn)
    by_verdict: dict[str, int] = {}
    for row in rows:
        by_verdict[row["target_eligible"]] = by_verdict.get(row["target_eligible"], 0) + 1
    print("opportunities:", len(rows), by_verdict)
    return 0


def cmd_benchmark(settings: Settings, args: argparse.Namespace) -> int:
    from .benchmark import run_benchmark

    return run_benchmark(settings, args.model, Path(args.labels), args.limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scholarship-radar")
    parser.add_argument("--root", default=".", help="project root containing config/ and data/")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    p = sub.add_parser("discover")
    p.add_argument("--skip-search", action="store_true")
    p.set_defaults(func=cmd_discover)
    p = sub.add_parser("fetch")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("extract")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("publish")
    p.add_argument("--send-test", action="store_true", help="email the full digest regardless of settings")
    p.set_defaults(func=cmd_publish)
    p = sub.add_parser("run")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--skip-search", action="store_true")
    p.add_argument("--skip-llm", action="store_true")
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_run)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p = sub.add_parser("benchmark")
    p.add_argument("--model", required=True)
    p.add_argument("--labels", default="benchmark/labels.yaml")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_benchmark)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    settings = load_settings(_root(args))
    return args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())

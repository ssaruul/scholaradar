from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import webbrowser
from dataclasses import asdict
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db
from .config import Settings, load_secrets, load_settings
from .fetch import Fetcher
from .llm.client import LlmClient
from .llm.extract import extract_pages
from .llm.server import LlamaServer, LlamaSettings, default_install_dir, install_llama
from .pipeline import discover, fetch_pages
from .publish.dedupe import group_opportunities
from .publish.run import post_social, publish_all, social_rows

log = logging.getLogger("scholaradar")


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


def open_dashboard(settings: Settings) -> None:
    index = settings.outputs.site.dir / "index.html"
    if index.exists():
        webbrowser.open(index.resolve().as_uri())
        print(f"opened {index}")
    else:
        print(f"no dashboard yet at {index}; run `scholaradar run` first")


def cmd_publish(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    run_id = db.start_run(conn)
    stats = publish_all(conn, settings, load_secrets(settings.root_dir), run_id, date.today(), force_email=args.send_test)
    db.finish_run(conn, run_id, asdict(stats))
    conn.commit()
    print(asdict(stats))
    if args.open:
        open_dashboard(settings)
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
    if args.open:
        open_dashboard(settings)
    return 0


def _llama(settings: Settings) -> LlamaServer:
    return LlamaServer(settings.root_dir, LlamaSettings(_env_file=str(settings.root_dir / ".env")))


def cmd_llm(settings: Settings, args: argparse.Namespace) -> int:
    if args.action == "install":
        install_llama(args.backend, Path(args.dest) if args.dest else default_install_dir())
        return 0
    server = _llama(settings)
    if args.action == "start":
        server.start()
    elif args.action == "stop":
        server.stop()
    else:
        print("healthy" if server.healthy() else "not running")
    return 0


def cmd_nightly(settings: Settings, args: argparse.Namespace) -> int:
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    searx = subprocess.run(["docker", "compose", "up", "-d", "searxng"], cwd=settings.root_dir, capture_output=True, text=True)
    if searx.returncode != 0:
        log.warning("searxng not started, search discovery will be skipped: %s", searx.stderr.strip()[-200:])
    server = _llama(settings)
    try:
        server.start()
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        log.warning("LLM not started (%s); running without extraction", exc)
    status = 0
    try:
        status = cmd_run(settings, args)
    finally:
        server.stop()
    return status


def cmd_social(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    today = date.today()
    rows = group_opportunities(db.opportunities(conn), today)
    if args.since_last_run:
        last = conn.execute("SELECT started FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            new_ids = {row["id"] for row in db.opportunities(conn, since=last["started"])}
            rows = [row for row in rows if set(row["group_ids"]) & new_ids]
    options = getattr(settings.outputs, args.channel)
    candidates = social_rows(conn, args.channel, rows, today, options.only_eligible)
    if args.limit:
        candidates = candidates[: args.limit]
    posted = post_social(conn, settings, load_secrets(settings.root_dir), args.channel, candidates, today, dry_run=args.dry_run)
    print(f"{args.channel}: {posted} items {'previewed' if args.dry_run else 'posted'}, {len(candidates)} candidates")
    return 0


def cmd_open(settings: Settings, args: argparse.Namespace) -> int:
    open_dashboard(settings)
    return 0


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    directory = settings.outputs.site.dir
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"serving {directory} at {url} (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
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
    parser = argparse.ArgumentParser(prog="scholaradar")
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
    p.add_argument("--open", action="store_true", help="open the dashboard in your browser afterwards")
    p.set_defaults(func=cmd_publish)
    for name, func in (("run", cmd_run), ("nightly", cmd_nightly)):
        p = sub.add_parser(name)
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--skip-search", action="store_true")
        p.add_argument("--skip-llm", action="store_true")
        p.add_argument("--model", default=None)
        p.add_argument("--open", action="store_true", help="open the dashboard in your browser afterwards")
        p.set_defaults(func=func)
    p = sub.add_parser("llm")
    p.add_argument("action", choices=["start", "stop", "status", "install"])
    p.add_argument("--backend", default="vulkan", help="install: vulkan | cuda-12.8 | cuda-13.4 | rocm | cpu")
    p.add_argument("--dest", default=None, help="install: directory to unpack llama.cpp into")
    p.set_defaults(func=cmd_llm)
    p = sub.add_parser("social")
    p.add_argument("channel", choices=["facebook", "telegram"])
    p.add_argument("--dry-run", action="store_true", help="print the post instead of sending it")
    p.add_argument("--since-last-run", action="store_true", help="only items first seen since the previous run")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_social)
    sub.add_parser("open").set_defaults(func=cmd_open)
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_serve)
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

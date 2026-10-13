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
from .drafting import KINDS, draft, load_profile, write_draft
from .fetch import Fetcher
from .labs import find_labs, render_labs, write_labs
from .llm.client import LlmClient
from .llm.extract import extract_pages
from .llm.server import LlamaServer, LlamaSettings, default_install_dir, install_llama
from .outreach import STATUSES, render_outreach
from .pipeline import discover, fetch_pages
from .planner import build_plan, render_plan, slugify, write_plan_ics
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
    stats = discover(
        conn, settings, fetcher, run_id, date.today(), skip_search=args.skip_search
    )
    fetcher.close()
    db.finish_run(conn, run_id, asdict(stats))
    conn.commit()
    print(asdict(stats))
    return 0


def cmd_fetch(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    fetcher = Fetcher(settings.fetch)
    stats = fetch_pages(
        conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run
    )
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
    stats = publish_all(
        conn,
        settings,
        load_secrets(settings.root_dir),
        run_id,
        date.today(),
        force_email=args.send_test,
    )
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
    discover_stats = discover(
        conn, settings, fetcher, run_id, today, skip_search=args.skip_search
    )
    log.info("discover: %s", asdict(discover_stats))
    fetch_stats = fetch_pages(
        conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run
    )
    log.info("fetch: %s", asdict(fetch_stats))
    if fetch_stats.links_added:
        link_stats = fetch_pages(
            conn, settings, fetcher, args.limit or settings.fetch.max_pages_per_run
        )
        log.info("fetch (followed links): %s", asdict(link_stats))
    fetcher.close()
    counts: dict[str, object] = {
        "discover": asdict(discover_stats),
        "fetch": asdict(fetch_stats),
    }
    if not args.skip_llm:
        client = LlmClient(settings.llm, model=args.model)
        if client.healthy():
            extract_stats = extract_pages(
                conn, settings, client, args.limit or 10_000, today
            )
            log.info("extract: %s", asdict(extract_stats))
            counts["extract"] = asdict(extract_stats)
        else:
            log.warning(
                "LLM endpoint not reachable at %s, skipping extraction",
                settings.llm.base_url,
            )
        client.close()
    publish_stats = publish_all(
        conn, settings, load_secrets(settings.root_dir), run_id, today
    )
    counts["publish"] = asdict(publish_stats)
    db.finish_run(conn, run_id, counts)
    conn.commit()
    print(counts)
    if args.open:
        open_dashboard(settings)
    return 0


def _llama(settings: Settings) -> LlamaServer:
    return LlamaServer(
        settings.root_dir, LlamaSettings(_env_file=str(settings.root_dir / ".env"))
    )


def cmd_llm(settings: Settings, args: argparse.Namespace) -> int:
    if args.action == "install":
        install_llama(
            args.backend, Path(args.dest) if args.dest else default_install_dir()
        )
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
    searx = subprocess.run(
        ["docker", "compose", "up", "-d", "searxng"],
        cwd=settings.root_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if searx.returncode != 0:
        log.warning(
            "searxng not started, search discovery will be skipped: %s",
            searx.stderr.strip()[-200:],
        )
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
        last = conn.execute(
            "SELECT started FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            new_ids = {
                row["id"] for row in db.opportunities(conn, since=last["started"])
            }
            rows = [row for row in rows if set(row["group_ids"]) & new_ids]
    options = getattr(settings.outputs, args.channel)
    candidates = social_rows(conn, args.channel, rows, today, options.only_eligible)
    if args.limit:
        candidates = candidates[: args.limit]
    posted = post_social(
        conn,
        settings,
        load_secrets(settings.root_dir),
        args.channel,
        candidates,
        today,
        dry_run=args.dry_run,
    )
    print(
        f"{args.channel}: {posted} items {'previewed' if args.dry_run else 'posted'}, {len(candidates)} candidates"
    )
    return 0


def cmd_open(settings: Settings, args: argparse.Namespace) -> int:
    open_dashboard(settings)
    return 0


def _find_opportunity(conn, ref: str | None) -> dict | None:
    if not ref:
        return None
    rows = db.opportunities(conn, include_dismissed=True)
    if ref.isdigit():
        return next((r for r in rows if r["id"] == int(ref)), None)
    needle = ref.casefold()
    today = date.today().isoformat()
    matches = [
        r
        for r in rows
        if needle in (r["page_url"] or "").casefold()
        or needle in (r["apply_url"] or "").casefold()
        or needle in (r["title"] or "").casefold()
        or needle in (r["canonical_name"] or "").casefold()
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda r: (
            not (r["deadline"] or "") >= today,
            (r["canonical_name"] or "").casefold() != needle,
            r["lang"] != "en",
            r["deadline"] or "9999",
        )
    )
    return matches[0]


def cmd_labs(settings: Settings, args: argparse.Namespace) -> int:
    secrets = load_secrets(settings.root_dir)
    mailto = secrets.digest_to or secrets.smtp_user or "scholaradar@example.org"
    institution, labs = find_labs(
        args.field, args.university, args.years, args.limit, args.min_works, mailto
    )
    content = render_labs(institution, labs, args.field, args.years)
    path = write_labs(
        settings.data_dir / "labs", institution, labs, args.field, args.years
    )
    print(content)
    print(f"saved to {path}")
    return 0


def cmd_plan(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    opportunity = _find_opportunity(conn, args.opportunity)
    deadline_text = args.deadline or (opportunity or {}).get("deadline")
    if not deadline_text:
        print("no deadline known; pass --deadline YYYY-MM-DD", file=sys.stderr)
        return 2
    deadline = date.fromisoformat(deadline_text)
    title = (
        (opportunity or {}).get("canonical_name")
        or (opportunity or {}).get("title")
        or args.title
        or "Application"
    )
    route = args.route or (opportunity or {}).get("application_route") or "unclear"
    documents = (opportunity or {}).get("required_documents") or []
    items = build_plan(deadline, args.lang, route, documents, date.today())
    content = render_plan(
        title, deadline, items, args.lang, (opportunity or {}).get("page_url", "")
    )
    out_dir = settings.data_dir / "plans"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{slugify(title)}-{deadline.isoformat()}"
    base.with_suffix(".md").write_text(content, encoding="utf-8")
    write_plan_ics(base.with_suffix(".ics"), title, items)
    print(content)
    print(f"saved to {base.with_suffix('.md')} and {base.with_suffix('.ics')}")
    return 0


def cmd_draft(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    profile = load_profile(Path(args.profile))
    opportunity = _find_opportunity(conn, args.opportunity)
    professor = None
    if args.professor:
        professor = {
            "name": args.professor,
            "university": args.university or "",
            "lab_topic": args.lab_topic or "",
            "recent_paper": args.paper or "",
        }
    client = LlmClient(settings.llm)
    if not client.healthy():
        print(
            f"LLM endpoint not reachable at {settings.llm.base_url}; run `scholaradar llm start` first",
            file=sys.stderr,
        )
        return 2
    content = draft(
        client,
        args.kind,
        profile,
        opportunity,
        professor,
        args.lang,
        settings.target.name,
        date.today(),
    )
    client.close()
    label = (
        (opportunity or {}).get("canonical_name")
        or (professor or {}).get("name")
        or profile.get("name", "draft")
    )
    path = write_draft(
        settings.data_dir / "drafts", args.kind, label, args.lang, content
    )
    print(content)
    print(f"saved to {path}")
    return 0


def cmd_outreach(settings: Settings, args: argparse.Namespace) -> int:
    conn = db.connect(settings.db_path)
    if args.action == "add":
        opportunity = _find_opportunity(conn, args.opportunity)
        new_id = db.add_outreach(
            conn,
            args.professor,
            args.university or "",
            args.email or "",
            args.lab_url or "",
            args.field or "",
            (opportunity or {}).get("id"),
            args.note or "",
        )
        print(f"added outreach #{new_id} for {args.professor}")
    elif args.action == "remove":
        if not args.id:
            print("pass --id", file=sys.stderr)
            return 2
        print(
            "removed"
            if db.remove_outreach(conn, args.id)
            else f"no outreach #{args.id}"
        )
    elif args.action in STATUSES[1:]:
        if not args.id:
            print("pass --id", file=sys.stderr)
            return 2
        print(
            "updated"
            if db.set_outreach_status(conn, args.id, args.action, args.note)
            else f"no outreach #{args.id}"
        )
    print(render_outreach(db.list_outreach(conn), date.today(), args.lang))
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
        by_verdict[row["target_eligible"]] = (
            by_verdict.get(row["target_eligible"], 0) + 1
        )
    print("opportunities:", len(rows), by_verdict)
    return 0


def cmd_benchmark(settings: Settings, args: argparse.Namespace) -> int:
    from .benchmark import run_benchmark

    return run_benchmark(settings, args.model, Path(args.labels), args.limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scholaradar")
    parser.add_argument(
        "--root", default=".", help="project root containing config/ and data/"
    )
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
    p.add_argument(
        "--send-test",
        action="store_true",
        help="email the full digest regardless of settings",
    )
    p.add_argument(
        "--open",
        action="store_true",
        help="open the dashboard in your browser afterwards",
    )
    p.set_defaults(func=cmd_publish)
    for name, func in (("run", cmd_run), ("nightly", cmd_nightly)):
        p = sub.add_parser(name)
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--skip-search", action="store_true")
        p.add_argument("--skip-llm", action="store_true")
        p.add_argument("--model", default=None)
        p.add_argument(
            "--open",
            action="store_true",
            help="open the dashboard in your browser afterwards",
        )
        p.set_defaults(func=func)
    p = sub.add_parser("llm")
    p.add_argument("action", choices=["start", "stop", "status", "install"])
    p.add_argument(
        "--backend",
        default="vulkan",
        help="install: vulkan | cuda-12.8 | cuda-13.4 | rocm | cpu",
    )
    p.add_argument(
        "--dest", default=None, help="install: directory to unpack llama.cpp into"
    )
    p.set_defaults(func=cmd_llm)
    p = sub.add_parser("social")
    p.add_argument("channel", choices=["facebook", "telegram"])
    p.add_argument(
        "--dry-run", action="store_true", help="print the post instead of sending it"
    )
    p.add_argument(
        "--since-last-run",
        action="store_true",
        help="only items first seen since the previous run",
    )
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_social)
    p = sub.add_parser(
        "labs", help="find professors at a university working on a field (OpenAlex)"
    )
    p.add_argument("--field", required=True)
    p.add_argument("--university", required=True)
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--min-works", type=int, default=10)
    p.set_defaults(func=cmd_labs)
    p = sub.add_parser(
        "plan", help="backward timeline from a deadline, as Markdown and .ics"
    )
    p.add_argument(
        "--opportunity",
        default=None,
        help="opportunity id, URL fragment or title fragment",
    )
    p.add_argument("--deadline", default=None)
    p.add_argument("--title", default=None)
    p.add_argument(
        "--route",
        default=None,
        choices=["embassy", "university", "online_portal", "email", "unclear"],
    )
    p.add_argument("--lang", default="mn", choices=["en", "mn"])
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser(
        "draft",
        help="draft an email, research plan, statement of purpose or CV with the local model",
    )
    p.add_argument("kind", choices=list(KINDS))
    p.add_argument("--profile", default="config/profile.yaml")
    p.add_argument("--opportunity", default=None)
    p.add_argument("--professor", default=None)
    p.add_argument("--university", default=None)
    p.add_argument("--lab-topic", default=None)
    p.add_argument(
        "--paper",
        default=None,
        help="title of a recent paper from the lab to reference",
    )
    p.add_argument("--lang", default="en", choices=["en", "ja", "mn"])
    p.set_defaults(func=cmd_draft)
    p = sub.add_parser("outreach", help="track emails to professors")
    p.add_argument(
        "action",
        choices=["list", "add", "sent", "replied", "accepted", "declined", "remove"],
    )
    p.add_argument("--id", type=int, default=0)
    p.add_argument("--professor", default=None)
    p.add_argument("--university", default=None)
    p.add_argument("--email", default=None)
    p.add_argument("--lab-url", default=None)
    p.add_argument("--field", default=None)
    p.add_argument("--opportunity", default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--lang", default="en", choices=["en", "mn"])
    p.set_defaults(func=cmd_outreach)
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
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    settings = load_settings(_root(args))
    return args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date

from .. import db
from ..config import Secrets, Settings
from .csv_export import write_csv
from .dedupe import group_opportunities
from .email_digest import render_digest, send_digest, smtp_configured
from .feeds import write_ics, write_rss
from .gitsync import sync_outputs
from .overrides import apply_overrides, load_overrides
from .report import render_report, write_report
from .sheets import push_to_sheets
from .site import write_badges, write_site
from .social import FacebookPage, TelegramChannel, format_digest

log = logging.getLogger(__name__)


@dataclass
class PublishStats:
    rows: int = 0
    new_rows: int = 0
    csv: int = 0
    site: int = 0
    report: str = ""
    git: bool = False
    facebook: int = 0
    telegram: int = 0
    emailed: int = 0
    sheets: int = 0


def _funded(rows: list[dict], funding: list[str]) -> list[dict]:
    if not funding:
        return rows
    return [row for row in rows if row["funding_type"] in funding]


def _upcoming(rows: list[dict], today: date) -> list[dict]:
    cutoff = today.isoformat()
    return [row for row in rows if row["deadline"] is None or row["deadline"] >= cutoff]


def social_rows(conn: sqlite3.Connection, channel: str, new_rows: list[dict], today: date, only_eligible: bool) -> list[dict]:
    candidates = [r for r in _upcoming(new_rows, today) if r["target_eligible"] == "yes" or (not only_eligible and r["target_eligible"] != "no")]
    candidates.sort(key=lambda r: (r["deadline"] or "9999", r["title"]))
    posted = {row["opportunity_id"] for row in conn.execute("SELECT opportunity_id FROM social_posts WHERE channel=?", (channel,))}
    return [r for r in candidates if not set(r.get("group_ids", [r["id"]])) & posted]


def post_social(conn: sqlite3.Connection, settings: Settings, secrets: Secrets, channel: str, rows: list[dict], today: date, dry_run: bool = False) -> int:
    options = getattr(settings.outputs, channel)
    if not rows:
        log.info("%s: nothing new to post", channel)
        return 0
    message, ids = format_digest(rows, settings.target.name, today, settings.outputs.site.pages_url, options.max_items, options.language)
    if dry_run:
        print(message)
        return len(ids)
    if channel == "facebook":
        if not (options.page_id and secrets.facebook_page_token):
            log.warning("facebook enabled but FACEBOOK_PAGE_ID/FACEBOOK_PAGE_TOKEN not set in .env")
            return 0
        result = FacebookPage(options.page_id, secrets.facebook_page_token, options.graph_version).post(message, settings.outputs.site.pages_url or None)
    else:
        if not (options.chat_id and secrets.telegram_bot_token):
            log.warning("telegram enabled but TELEGRAM_CHAT_ID/TELEGRAM_BOT_TOKEN not set in .env")
            return 0
        result = TelegramChannel(secrets.telegram_bot_token, options.chat_id).post(message)
    if not result.ok:
        log.warning("%s post failed: %s", channel, result.error)
        return 0
    member_ids = [member for row in rows if row["id"] in ids for member in row.get("group_ids", [row["id"]])]
    db.mark_posted(conn, channel, member_ids, result.external_id)
    log.info("%s: posted %d items (%s)", channel, len(ids), result.external_id)
    return len(ids)


def publish_all(conn: sqlite3.Connection, settings: Settings, secrets: Secrets, run_id: int, today: date, force_email: bool = False) -> PublishStats:
    stats = PublishStats()
    rows = apply_overrides(db.opportunities(conn), load_overrides(settings.root_dir / "config" / "overrides.yaml"))
    stats.rows = len(rows)
    outputs = settings.outputs
    previous = db.previous_run_started(conn, run_id)
    new_ids = {row["id"] for row in (db.opportunities(conn, since=previous) if previous else rows)}
    grouped = group_opportunities(rows, today)
    shown = _funded(grouped, outputs.funding)
    new_rows = [group for group in shown if set(group["group_ids"]) & new_ids]
    stats.new_rows = len(new_rows)
    if outputs.csv.enabled:
        stats.csv = write_csv(outputs.csv.path, rows)
        log.info("csv: %d rows -> %s", stats.csv, outputs.csv.path)
    if outputs.site.enabled:
        index = write_site(outputs.site.dir, settings.templates_dir, grouped, settings.target.name, today, outputs.site.repo_url, outputs.funding)
        stats.site = len(shown)
        write_rss(outputs.site.dir / "feed.xml", shown, settings.target.name, outputs.site.pages_url, today)
        write_ics(outputs.site.dir / "deadlines.ics", shown, settings.target.name, today)
        write_badges(outputs.site.dir, len(shown), sum(1 for r in shown if r["target_eligible"] == "yes"), today, "fully funded" if outputs.funding == ["full"] else "opportunities")
        log.info("site: %s (+ feed.xml, deadlines.ics)", index)
    if outputs.report.enabled:
        content = render_report(shown, new_rows, settings.target.name, today, outputs.site.pages_url, outputs.report.window_days, db.changes_since(conn, previous), outputs.funding)
        stats.report = str(write_report(outputs.report.dir, content, today))
        log.info("report: %s", stats.report)
    for channel in ("facebook", "telegram"):
        if getattr(outputs, channel).enabled:
            rows_to_post = social_rows(conn, channel, new_rows, today, getattr(outputs, channel).only_eligible)
            setattr(stats, channel, post_social(conn, settings, secrets, channel, rows_to_post, today))
    if outputs.git.enabled:
        stats.git = sync_outputs(
            settings.root_dir,
            [outputs.site.dir, outputs.csv.path, outputs.report.dir],
            f"Report {today.isoformat()}: {stats.new_rows} new, {len(rows)} tracked",
            outputs.git.remote,
            outputs.git.branch,
            outputs.git.push,
        )
    if outputs.email.enabled or force_email:
        digest_rows = _upcoming(new_rows if outputs.email.only_new and not force_email else shown, today)
        if not smtp_configured(secrets):
            log.warning("email enabled but SMTP_HOST/DIGEST_TO not set in .env")
        elif digest_rows or force_email:
            html, text = render_digest(settings.templates_dir, digest_rows, settings.target.name, today)
            subject = f"{outputs.email.subject_prefix} {len(digest_rows)} opportunities, {today.isoformat()}"
            send_digest(secrets, subject, html, text)
            stats.emailed = len(digest_rows)
            log.info("email: sent %d rows to %s", stats.emailed, secrets.digest_to)
    if outputs.sheets.enabled:
        stats.sheets = push_to_sheets(outputs.sheets.credentials_file, outputs.sheets.spreadsheet_id, outputs.sheets.worksheet, rows)
        log.info("sheets: %d rows", stats.sheets)
    return stats

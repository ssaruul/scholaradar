from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date

from .. import db
from ..config import Secrets, Settings
from .csv_export import write_csv
from .email_digest import render_digest, send_digest, smtp_configured
from .gitsync import sync_outputs
from .report import render_report, write_report
from .sheets import push_to_sheets
from .site import write_site

log = logging.getLogger(__name__)


@dataclass
class PublishStats:
    rows: int = 0
    new_rows: int = 0
    csv: int = 0
    site: int = 0
    report: str = ""
    git: bool = False
    emailed: int = 0
    sheets: int = 0


def _upcoming(rows: list[dict], today: date) -> list[dict]:
    cutoff = today.isoformat()
    return [row for row in rows if row["deadline"] is None or row["deadline"] >= cutoff]


def publish_all(conn: sqlite3.Connection, settings: Settings, secrets: Secrets, run_id: int, today: date, force_email: bool = False) -> PublishStats:
    stats = PublishStats()
    rows = db.opportunities(conn)
    stats.rows = len(rows)
    outputs = settings.outputs
    previous = db.previous_run_started(conn, run_id)
    new_rows = db.opportunities(conn, since=previous) if previous else rows
    stats.new_rows = len(new_rows)
    if outputs.csv.enabled:
        stats.csv = write_csv(outputs.csv.path, rows)
        log.info("csv: %d rows -> %s", stats.csv, outputs.csv.path)
    if outputs.site.enabled:
        index = write_site(outputs.site.dir, settings.templates_dir, rows, settings.target.name, today)
        stats.site = len(rows)
        log.info("site: %s", index)
    if outputs.report.enabled:
        content = render_report(rows, new_rows, settings.target.name, today, outputs.site.pages_url, outputs.report.window_days)
        stats.report = str(write_report(outputs.report.dir, content, today))
        log.info("report: %s", stats.report)
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
        digest_rows = _upcoming(new_rows if outputs.email.only_new and not force_email else rows, today)
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

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    kind TEXT NOT NULL,
    lang TEXT NOT NULL,
    follow_links INTEGER NOT NULL DEFAULT 0,
    implies_eligible INTEGER NOT NULL DEFAULT 0,
    render INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    source_id INTEGER REFERENCES sources(id),
    discovered_via TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_fetched TEXT,
    http_status INTEGER,
    content_hash TEXT,
    text_path TEXT,
    title TEXT,
    lang TEXT,
    nationality_hits TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    error TEXT
);
CREATE INDEX IF NOT EXISTS pages_status ON pages(status);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL UNIQUE REFERENCES pages(id),
    title TEXT NOT NULL,
    canonical_name TEXT,
    provider TEXT,
    host_country TEXT,
    degree_levels TEXT,
    fields_of_study TEXT,
    funding_type TEXT,
    deadline TEXT,
    deadline_text TEXT,
    eligibility_summary TEXT,
    nationality_mode TEXT,
    target_eligible TEXT NOT NULL,
    evidence_quote TEXT,
    evidence_verified INTEGER NOT NULL DEFAULT 0,
    apply_url TEXT,
    lang TEXT,
    model TEXT,
    extracted_at TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS search_hits (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    query TEXT NOT NULL,
    lang TEXT NOT NULL,
    url TEXT NOT NULL,
    rank INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS social_posts (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    posted_at TEXT NOT NULL,
    external_id TEXT,
    UNIQUE(channel, opportunity_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    counts TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class PageRow:
    id: int
    canonical_url: str
    url: str
    source_id: int | None
    discovered_via: str
    text_path: str | None
    title: str | None
    lang: str | None
    nationality_hits: list[str]
    status: str
    last_fetched: str | None
    content_hash: str | None


@dataclass
class OpportunityRecord:
    page_id: int
    title: str
    provider: str
    host_country: str
    degree_levels: list[str]
    fields_of_study: list[str]
    funding_type: str
    deadline: str | None
    deadline_text: str
    eligibility_summary: str
    nationality_mode: str
    target_eligible: str
    evidence_quote: str
    evidence_verified: bool
    apply_url: str
    lang: str
    model: str
    canonical_name: str = ""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
    if "implies_eligible" not in columns:
        conn.execute("ALTER TABLE sources ADD COLUMN implies_eligible INTEGER NOT NULL DEFAULT 0")
    if "render" not in columns:
        conn.execute("ALTER TABLE sources ADD COLUMN render INTEGER NOT NULL DEFAULT 0")
    opportunity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)")}
    if "canonical_name" not in opportunity_columns:
        conn.execute("ALTER TABLE opportunities ADD COLUMN canonical_name TEXT")
    return conn


def upsert_source(conn: sqlite3.Connection, name: str, url: str, kind: str, lang: str, follow_links: bool, implies_eligible: bool, enabled: bool, render: bool = False) -> int:
    conn.execute(
        """INSERT INTO sources(name, url, kind, lang, follow_links, implies_eligible, enabled, render) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET url=excluded.url, kind=excluded.kind, lang=excluded.lang,
           follow_links=excluded.follow_links, implies_eligible=excluded.implies_eligible, enabled=excluded.enabled, render=excluded.render""",
        (name, url, kind, lang, int(follow_links), int(implies_eligible), int(enabled), int(render)),
    )
    row = conn.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()
    return int(row["id"])


def touch_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("UPDATE sources SET last_checked=? WHERE id=?", (now_iso(), source_id))


def add_page(conn: sqlite3.Connection, url: str, canonical_url: str, source_id: int | None, discovered_via: str) -> tuple[int, bool]:
    cur = conn.execute(
        "INSERT OR IGNORE INTO pages(canonical_url, url, source_id, discovered_via, first_seen) VALUES (?, ?, ?, ?, ?)",
        (canonical_url, url, source_id, discovered_via, now_iso()),
    )
    if cur.rowcount:
        return int(cur.lastrowid), True
    row = conn.execute("SELECT id FROM pages WHERE canonical_url=?", (canonical_url,)).fetchone()
    return int(row["id"]), False


def requeue_page(conn: sqlite3.Connection, page_id: int) -> None:
    conn.execute("UPDATE pages SET status='new' WHERE id=?", (page_id,))


def adopt_as_source(conn: sqlite3.Connection, page_id: int, source_id: int, url: str) -> None:
    conn.execute("UPDATE pages SET source_id=?, url=?, discovered_via='source', status='new', error=NULL WHERE id=?", (source_id, url, page_id))


def _page_from_row(row: sqlite3.Row) -> PageRow:
    hits = json.loads(row["nationality_hits"]) if row["nationality_hits"] else []
    return PageRow(
        id=row["id"],
        canonical_url=row["canonical_url"],
        url=row["url"],
        source_id=row["source_id"],
        discovered_via=row["discovered_via"],
        text_path=row["text_path"],
        title=row["title"],
        lang=row["lang"],
        nationality_hits=hits,
        status=row["status"],
        last_fetched=row["last_fetched"],
        content_hash=row["content_hash"],
    )


def pages_with_status(conn: sqlite3.Connection, status: str, limit: int) -> list[PageRow]:
    rows = conn.execute("SELECT * FROM pages WHERE status=? ORDER BY id LIMIT ?", (status, limit)).fetchall()
    return [_page_from_row(row) for row in rows]


def get_page(conn: sqlite3.Connection, page_id: int) -> PageRow:
    row = conn.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    return _page_from_row(row)


def source_pages_to_recheck(conn: sqlite3.Connection, older_than_hours: int) -> list[PageRow]:
    rows = conn.execute(
        """SELECT * FROM pages WHERE discovered_via='source' AND status<>'new'
           AND (last_fetched IS NULL OR last_fetched < datetime('now', ?))""",
        (f"-{older_than_hours} hours",),
    ).fetchall()
    return [_page_from_row(row) for row in rows]


def mark_fetched(
    conn: sqlite3.Connection,
    page_id: int,
    http_status: int,
    content_hash: str,
    text_path: str,
    title: str,
    lang: str,
    nationality_hits: list[str],
    status: str,
) -> None:
    conn.execute(
        """UPDATE pages SET last_fetched=?, http_status=?, content_hash=?, text_path=?, title=?, lang=?,
           nationality_hits=?, status=?, error=NULL WHERE id=?""",
        (now_iso(), http_status, content_hash, text_path, title, lang, json.dumps(nationality_hits, ensure_ascii=False), status, page_id),
    )


def mark_page_error(conn: sqlite3.Connection, page_id: int, http_status: int | None, error: str, status: str = "error") -> None:
    conn.execute(
        "UPDATE pages SET last_fetched=?, http_status=?, status=?, error=? WHERE id=?",
        (now_iso(), http_status, status, error[:500], page_id),
    )


def requeue_llm_errors(conn: sqlite3.Connection) -> int:
    cur = conn.execute("UPDATE pages SET status='fetched' WHERE status='error' AND error LIKE 'llm:%'")
    conn.commit()
    return cur.rowcount


def set_page_status(conn: sqlite3.Connection, page_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE pages SET status=?, error=? WHERE id=?", (status, error, page_id))


def source_follow_links(conn: sqlite3.Connection, source_id: int | None) -> bool:
    if source_id is None:
        return False
    row = conn.execute("SELECT follow_links FROM sources WHERE id=?", (source_id,)).fetchone()
    return bool(row and row["follow_links"])


def source_renders(conn: sqlite3.Connection, source_id: int | None) -> bool:
    if source_id is None:
        return False
    row = conn.execute("SELECT render FROM sources WHERE id=?", (source_id,)).fetchone()
    return bool(row and row["render"])


def source_implying_eligibility(conn: sqlite3.Connection, source_id: int | None) -> str | None:
    if source_id is None:
        return None
    row = conn.execute("SELECT name, implies_eligible FROM sources WHERE id=?", (source_id,)).fetchone()
    return row["name"] if row and row["implies_eligible"] else None


TRACKED_FIELDS = ("deadline", "target_eligible", "funding_type")


def upsert_opportunity(conn: sqlite3.Connection, rec: OpportunityRecord) -> list[tuple[str, str | None, str | None]]:
    now = now_iso()
    previous = conn.execute("SELECT id, deadline, target_eligible, funding_type FROM opportunities WHERE page_id=?", (rec.page_id,)).fetchone()
    changes: list[tuple[str, str | None, str | None]] = []
    if previous:
        for field in TRACKED_FIELDS:
            old, new = previous[field], getattr(rec, field)
            if old != new:
                changes.append((field, old, new))
    conn.execute(
        """INSERT INTO opportunities(page_id, title, provider, host_country, degree_levels, fields_of_study, funding_type,
           deadline, deadline_text, eligibility_summary, nationality_mode, target_eligible, evidence_quote, evidence_verified,
           apply_url, lang, model, extracted_at, first_seen, canonical_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(page_id) DO UPDATE SET title=excluded.title, provider=excluded.provider, host_country=excluded.host_country, canonical_name=excluded.canonical_name,
           degree_levels=excluded.degree_levels, fields_of_study=excluded.fields_of_study, funding_type=excluded.funding_type,
           deadline=excluded.deadline, deadline_text=excluded.deadline_text, eligibility_summary=excluded.eligibility_summary,
           nationality_mode=excluded.nationality_mode, target_eligible=excluded.target_eligible, evidence_quote=excluded.evidence_quote,
           evidence_verified=excluded.evidence_verified, apply_url=excluded.apply_url, lang=excluded.lang, model=excluded.model,
           extracted_at=excluded.extracted_at""",
        (
            rec.page_id, rec.title, rec.provider, rec.host_country, json.dumps(rec.degree_levels), json.dumps(rec.fields_of_study, ensure_ascii=False),
            rec.funding_type, rec.deadline, rec.deadline_text, rec.eligibility_summary, rec.nationality_mode, rec.target_eligible,
            rec.evidence_quote, int(rec.evidence_verified), rec.apply_url, rec.lang, rec.model, now, now, rec.canonical_name,
        ),
    )
    if previous and changes:
        conn.executemany(
            "INSERT INTO changes(opportunity_id, field, old_value, new_value, changed_at) VALUES (?, ?, ?, ?, ?)",
            [(previous["id"], field, old, new, now) for field, old, new in changes],
        )
    return changes


def changes_since(conn: sqlite3.Connection, since: str | None) -> list[dict]:
    rows = conn.execute(
        """SELECT c.field, c.old_value, c.new_value, c.changed_at, o.title, o.apply_url, p.url AS page_url
           FROM changes c JOIN opportunities o ON o.id=c.opportunity_id JOIN pages p ON p.id=o.page_id
           WHERE (? IS NULL OR c.changed_at > ?) ORDER BY c.changed_at DESC""",
        (since, since),
    ).fetchall()
    return [dict(row) for row in rows]


def opportunities(conn: sqlite3.Connection, since: str | None = None, include_dismissed: bool = False) -> list[dict]:
    clauses = []
    params: list[object] = []
    if not include_dismissed:
        clauses.append("o.dismissed=0")
    if since:
        clauses.append("o.first_seen > ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""SELECT o.*, p.url AS page_url, p.discovered_via FROM opportunities o JOIN pages p ON p.id=o.page_id
            {where} ORDER BY CASE WHEN o.deadline IS NULL THEN 1 ELSE 0 END, o.deadline, o.first_seen DESC""",
        params,
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["degree_levels"] = json.loads(item["degree_levels"] or "[]")
        item["fields_of_study"] = json.loads(item["fields_of_study"] or "[]")
        item["evidence_verified"] = bool(item["evidence_verified"])
        result.append(item)
    return result


def unposted(conn: sqlite3.Connection, channel: str, rows: list[dict]) -> list[dict]:
    posted = {row["opportunity_id"] for row in conn.execute("SELECT opportunity_id FROM social_posts WHERE channel=?", (channel,))}
    return [row for row in rows if row["id"] not in posted]


def mark_posted(conn: sqlite3.Connection, channel: str, opportunity_ids: list[int], external_id: str | None) -> None:
    now = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO social_posts(channel, opportunity_id, posted_at, external_id) VALUES (?, ?, ?, ?)",
        [(channel, oid, now, external_id) for oid in opportunity_ids],
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs(started) VALUES (?)", (now_iso(),))
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, counts: dict[str, int]) -> None:
    conn.execute("UPDATE runs SET finished=?, counts=? WHERE id=?", (now_iso(), json.dumps(counts), run_id))


def previous_run_started(conn: sqlite3.Connection, current_run_id: int) -> str | None:
    row = conn.execute(
        "SELECT started FROM runs WHERE id<? AND finished IS NOT NULL ORDER BY id DESC LIMIT 1", (current_run_id,)
    ).fetchone()
    return row["started"] if row else None


def record_search_hit(conn: sqlite3.Connection, run_id: int, query: str, lang: str, url: str, rank: int) -> None:
    conn.execute("INSERT INTO search_hits(run_id, query, lang, url, rank) VALUES (?, ?, ?, ?, ?)", (run_id, query, lang, url, rank))


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM pages GROUP BY status").fetchall()
    return {row["status"]: row["n"] for row in rows}

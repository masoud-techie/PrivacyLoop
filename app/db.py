"""SQLite storage. Everything lives in one file on your disk and never leaves it."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "privacyloop.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    full_name       TEXT NOT NULL DEFAULT '',
    aliases         TEXT NOT NULL DEFAULT '',   -- maiden names, nicknames, one per line
    emails          TEXT NOT NULL DEFAULT '',   -- one per line
    phones          TEXT NOT NULL DEFAULT '',
    addresses       TEXT NOT NULL DEFAULT '',   -- current + past, one per line
    birth_year      TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT '',
    country         TEXT NOT NULL DEFAULT 'US',
    reply_email     TEXT NOT NULL DEFAULT '',
    traits          TEXT NOT NULL DEFAULT '[]', -- JSON list of trigger keys
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS broker_status (
    broker_id   TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'unknown',  -- unknown|found|not_found|skipped
    notes       TEXT NOT NULL DEFAULT '',
    checked_at  TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_id   TEXT NOT NULL,
    broker_name TEXT NOT NULL,
    action      TEXT NOT NULL,
    law         TEXT NOT NULL,
    channel     TEXT NOT NULL,          -- email|form
    to_email    TEXT NOT NULL DEFAULT '',
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'draft',
    -- draft|sent|acknowledged|completed|rejected|needs_action|expired
    created_at  TEXT NOT NULL,
    sent_at     TEXT,
    due_at      TEXT,
    closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_requests_broker ON requests(broker_id);
CREATE INDEX IF NOT EXISTS idx_events_request ON events(request_id);
"""

# Statutory response windows, in days.
RESPONSE_WINDOWS = {
    "CCPA": 45,   # Cal. Civ. Code 1798.130(a)(2) - extendable by another 45
    "CPA": 45,    # Colorado
    "VCDPA": 45,  # Virginia
    "CTDPA": 45,  # Connecticut
    "UCPA": 45,   # Utah
    "GDPR": 30,   # Art. 12(3) - one month, extendable by two
    "UK-GDPR": 30,
    "NONE": 45,   # no statute: use 45 days as a courtesy deadline anyway
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def due_date(law: str, sent: datetime | None = None) -> str:
    days = RESPONSE_WINDOWS.get(law, 45)
    base = sent or datetime.now(timezone.utc)
    return (base + timedelta(days=days)).isoformat(timespec="seconds")


@contextmanager
def connect():
    """Commit-and-close context manager.

    Note `with sqlite3.connect(...)` commits the transaction but leaves the
    connection open - on Windows that holds a lock on the .db file forever.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)")


def get_profile() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    p = dict(row) if row else {}
    try:
        p["traits"] = json.loads(p.get("traits") or "[]")
    except json.JSONDecodeError:
        p["traits"] = []
    return p


def save_profile(data: dict) -> None:
    fields = ["full_name", "aliases", "emails", "phones", "addresses",
              "birth_year", "state", "country", "reply_email"]
    values = [data.get(f, "").strip() for f in fields]
    values.append(json.dumps(data.get("traits", [])))
    values.append(now_iso())
    with connect() as conn:
        conn.execute(
            f"UPDATE profile SET {', '.join(f + ' = ?' for f in fields)},"
            " traits = ?, updated_at = ? WHERE id = 1",
            values,
        )


def all_status() -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM broker_status").fetchall()
    return {r["broker_id"]: dict(r) for r in rows}


def set_status(broker_id: str, state: str, notes: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO broker_status (broker_id, state, notes, checked_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(broker_id) DO UPDATE SET"
            " state = excluded.state, notes = excluded.notes,"
            " checked_at = excluded.checked_at",
            (broker_id, state, notes, now_iso()),
        )


def create_request(**kw) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO requests (broker_id, broker_name, action, law, channel,"
            " to_email, subject, body, status, created_at)"
            " VALUES (:broker_id, :broker_name, :action, :law, :channel,"
            " :to_email, :subject, :body, 'draft', :created_at)",
            {**kw, "created_at": now_iso()},
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO events (request_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
            (rid, now_iso(), "created", f"Draft created for {kw['broker_name']}"),
        )
    return rid


def get_request(rid: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (rid,)).fetchone()
        if not row:
            return None
        events = conn.execute(
            "SELECT * FROM events WHERE request_id = ? ORDER BY id DESC", (rid,)
        ).fetchall()
    out = dict(row)
    out["events"] = [dict(e) for e in events]
    return out


def list_requests(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM requests"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY COALESCE(sent_at, created_at) DESC"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def update_request(rid: int, **kw) -> None:
    if not kw:
        return
    sets = ", ".join(f"{k} = ?" for k in kw)
    with connect() as conn:
        conn.execute(f"UPDATE requests SET {sets} WHERE id = ?", (*kw.values(), rid))


def log_event(rid: int, kind: str, detail: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (request_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
            (rid, now_iso(), kind, detail),
        )


def mark_sent(rid: int, law: str, detail: str) -> None:
    sent = datetime.now(timezone.utc)
    update_request(
        rid,
        status="sent",
        sent_at=sent.isoformat(timespec="seconds"),
        due_at=due_date(law, sent),
    )
    log_event(rid, "sent", detail)


def overdue_requests() -> list[dict]:
    """Sent requests whose statutory response window has already elapsed."""
    today = now_iso()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM requests WHERE status IN ('sent', 'acknowledged')"
            " AND due_at IS NOT NULL AND due_at < ? ORDER BY due_at",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) n FROM requests GROUP BY status"
        ).fetchall()
        found = conn.execute(
            "SELECT COUNT(*) n FROM broker_status WHERE state = 'found'"
        ).fetchone()["n"]
    by_status = {r["status"]: r["n"] for r in rows}
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "found": found,
        "overdue": len(overdue_requests()),
    }

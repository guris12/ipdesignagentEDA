"""
Time-slot queue for the shared OpenROAD runner.

Only one student at a time may submit OpenROAD jobs — they hold an *active
slot*. Other students wait in FIFO order and see their position. Slots expire
after ``DEFAULT_TTL_SECONDS`` so a student who walks away doesn't hog the
runner forever.

State lives in one Postgres table, ``queue_slots``, created by ``start.sh``
at container boot. All reads and writes go through short-lived connections
via ``psycopg`` to avoid importing SQLAlchemy here.

Public API::

    claim_slot(identifier) -> SlotState
    release_slot(identifier) -> None
    position_of(identifier) -> Optional[int]   # 1 = has slot, 2+ = waiting
    active_slot() -> Optional[SlotState]
    state_for(identifier) -> QueueView
    cleanup_expired() -> int                    # returns number expired
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg


DEFAULT_TTL_SECONDS = 1200            # 20 min active slot
DEFAULT_WAIT_TTL_SECONDS = 1800       # drop abandoned waiters after 30 min
ACTIVE_STATUS = "active"
WAITING_STATUS = "waiting"


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------


def _conn_str() -> str:
    """Build a psycopg connection string.

    Prefers the ECS-style discrete env vars (DB_HOST, DB_CREDENTIALS, …) and
    falls back to parsing DATABASE_URL — which is what docker-compose and
    local .env files set.
    """
    if os.environ.get("DB_HOST"):
        db_host = os.environ["DB_HOST"]
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "ip_agent_db")
        creds = os.environ.get("DB_CREDENTIALS", "")
        if creds:
            c = json.loads(creds)
            user, pw = c["username"], c["password"]
        else:
            user = os.environ.get("DB_USERNAME", "ip_agent")
            pw = os.environ.get("DB_PASSWORD", "")
        return f"host={db_host} port={db_port} dbname={db_name} user={user} password={pw}"

    from urllib.parse import urlparse, unquote

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("No DB connection info: set DATABASE_URL or DB_HOST")
    # Normalise the SQLAlchemy-style prefix psycopg expects a plain URL.
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    parsed = urlparse(url)
    user = unquote(parsed.username or "")
    pw = unquote(parsed.password or "")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    db = (parsed.path or "/postgres").lstrip("/")
    return f"host={host} port={port} dbname={db} user={user} password={pw}"


def _connect() -> psycopg.Connection:
    return psycopg.connect(_conn_str(), autocommit=False)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SlotState:
    identifier: str
    status: str                    # "active" or "waiting"
    enqueued_at: datetime
    expires_at: datetime

    def to_json(self) -> dict:
        d = asdict(self)
        d["enqueued_at"] = self.enqueued_at.isoformat()
        d["expires_at"] = self.expires_at.isoformat()
        return d

    def seconds_remaining(self) -> int:
        return max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds()))


@dataclass
class QueueView:
    identifier: str
    status: str                    # "active" | "waiting" | "idle"
    position: Optional[int]        # 1 = active, 2+ = waiting, None = not in queue
    seconds_remaining: Optional[int]
    waiting_count: int
    eta_seconds: Optional[int]     # estimated wait to become active

    def to_json(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Table DDL — also duplicated in start.sh so ECS creates it on boot
# ---------------------------------------------------------------------------


QUEUE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS queue_slots (
    identifier   TEXT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN ('active', 'waiting')),
    enqueued_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS queue_slots_status_enqueued_idx
    ON queue_slots (status, enqueued_at);
"""


def ensure_table() -> None:
    """Idempotent — safe to call from anywhere."""
    with _connect() as conn:
        conn.execute(QUEUE_TABLE_DDL)
        conn.commit()


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _expire_stale(conn: psycopg.Connection) -> None:
    """Delete rows whose expires_at has passed. Runs inside a provided tx."""
    conn.execute("DELETE FROM queue_slots WHERE expires_at < NOW()")


def _promote_head_if_free(conn: psycopg.Connection) -> None:
    """If no slot is active, promote the oldest waiter to active."""
    row = conn.execute(
        "SELECT 1 FROM queue_slots WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if row is not None:
        return
    head = conn.execute(
        "SELECT identifier FROM queue_slots WHERE status = 'waiting' "
        "ORDER BY enqueued_at LIMIT 1"
    ).fetchone()
    if head is None:
        return
    (head_id,) = head
    conn.execute(
        "UPDATE queue_slots "
        "SET status = 'active', "
        "    enqueued_at = NOW(), "
        "    expires_at = NOW() + (%s || ' seconds')::interval "
        "WHERE identifier = %s",
        (DEFAULT_TTL_SECONDS, head_id),
    )


def claim_slot(identifier: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> SlotState:
    """Claim the slot if free, else join the queue. Idempotent for a given id."""
    if not identifier:
        raise ValueError("identifier is required")
    with _connect() as conn:
        with conn.transaction():
            _expire_stale(conn)

            existing = conn.execute(
                "SELECT status, enqueued_at, expires_at FROM queue_slots "
                "WHERE identifier = %s",
                (identifier,),
            ).fetchone()

            if existing is not None:
                status, enq, exp = existing
                # Touch waiter to extend its TTL; active slot keeps its timer.
                if status == WAITING_STATUS:
                    new_exp = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_WAIT_TTL_SECONDS)
                    conn.execute(
                        "UPDATE queue_slots SET expires_at = %s WHERE identifier = %s",
                        (new_exp, identifier),
                    )
                    exp = new_exp
                return SlotState(identifier, status, enq, exp)

            active = conn.execute(
                "SELECT 1 FROM queue_slots WHERE status = 'active' LIMIT 1"
            ).fetchone()
            if active is None:
                expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
                conn.execute(
                    "INSERT INTO queue_slots (identifier, status, expires_at) "
                    "VALUES (%s, 'active', %s)",
                    (identifier, expires),
                )
                return SlotState(identifier, ACTIVE_STATUS,
                                 datetime.now(timezone.utc), expires)

            expires = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_WAIT_TTL_SECONDS)
            conn.execute(
                "INSERT INTO queue_slots (identifier, status, expires_at) "
                "VALUES (%s, 'waiting', %s)",
                (identifier, expires),
            )
            return SlotState(identifier, WAITING_STATUS,
                             datetime.now(timezone.utc), expires)


def release_slot(identifier: str) -> bool:
    """Remove a student from the queue. Promotes the next waiter if needed."""
    with _connect() as conn:
        with conn.transaction():
            cur = conn.execute(
                "DELETE FROM queue_slots WHERE identifier = %s",
                (identifier,),
            )
            removed = cur.rowcount > 0
            _expire_stale(conn)
            _promote_head_if_free(conn)
            return removed


def active_slot() -> Optional[SlotState]:
    with _connect() as conn:
        with conn.transaction():
            _expire_stale(conn)
            _promote_head_if_free(conn)
            row = conn.execute(
                "SELECT identifier, status, enqueued_at, expires_at "
                "FROM queue_slots WHERE status = 'active' LIMIT 1"
            ).fetchone()
    if row is None:
        return None
    return SlotState(*row)


def position_of(identifier: str) -> Optional[int]:
    """1 = has slot, 2+ = position in queue, None = not enqueued."""
    with _connect() as conn:
        with conn.transaction():
            _expire_stale(conn)
            _promote_head_if_free(conn)
            row = conn.execute(
                """
                SELECT position
                FROM (
                    SELECT identifier,
                           ROW_NUMBER() OVER (
                               ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                                        enqueued_at
                           ) AS position
                    FROM queue_slots
                ) ranked
                WHERE identifier = %s
                """,
                (identifier,),
            ).fetchone()
    return int(row[0]) if row else None


def state_for(identifier: str) -> QueueView:
    with _connect() as conn:
        with conn.transaction():
            _expire_stale(conn)
            _promote_head_if_free(conn)
            row = conn.execute(
                "SELECT identifier, status, enqueued_at, expires_at "
                "FROM queue_slots WHERE identifier = %s",
                (identifier,),
            ).fetchone()
            waiting_count = conn.execute(
                "SELECT COUNT(*) FROM queue_slots WHERE status = 'waiting'"
            ).fetchone()[0]
            active_row = conn.execute(
                "SELECT expires_at FROM queue_slots WHERE status = 'active'"
            ).fetchone()
            ahead_row = None
            if row is not None and row[1] == WAITING_STATUS:
                ahead_row = conn.execute(
                    "SELECT COUNT(*) FROM queue_slots "
                    "WHERE status = 'waiting' AND enqueued_at < %s",
                    (row[2],),
                ).fetchone()

    if row is None:
        return QueueView(
            identifier=identifier,
            status="idle",
            position=None,
            seconds_remaining=None,
            waiting_count=int(waiting_count),
            eta_seconds=None,
        )

    slot = SlotState(*row)
    if slot.status == ACTIVE_STATUS:
        return QueueView(
            identifier=identifier,
            status="active",
            position=1,
            seconds_remaining=slot.seconds_remaining(),
            waiting_count=int(waiting_count),
            eta_seconds=0,
        )

    ahead = int(ahead_row[0]) if ahead_row else 0
    active_remaining = 0
    if active_row is not None:
        active_remaining = max(
            0,
            int((active_row[0] - datetime.now(timezone.utc)).total_seconds()),
        )
    eta = active_remaining + ahead * DEFAULT_TTL_SECONDS
    return QueueView(
        identifier=identifier,
        status="waiting",
        position=ahead + 2,
        seconds_remaining=slot.seconds_remaining(),
        waiting_count=int(waiting_count),
        eta_seconds=eta,
    )


def cleanup_expired() -> int:
    """Delete expired rows and promote the next waiter. Returns count removed."""
    with _connect() as conn:
        with conn.transaction():
            cur = conn.execute("DELETE FROM queue_slots WHERE expires_at < NOW()")
            removed = cur.rowcount or 0
            _promote_head_if_free(conn)
            return int(removed)

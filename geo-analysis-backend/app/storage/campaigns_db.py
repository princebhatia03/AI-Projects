"""Local SQLite persistence for campaign trigger history."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app import config

_lock = threading.Lock()
_INITIALIZED = False


def db_path() -> Path:
    raw = getattr(config, "CAMPAIGNS_DB_PATH", None) or "artifacts/campaigns.db"
    path = Path(raw)
    if not path.is_absolute():
        path = config.ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> Path:
    global _INITIALIZED
    path = db_path()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_history (
                    campaign_id TEXT PRIMARY KEY,
                    zip_code TEXT NOT NULL,
                    city TEXT,
                    offer_id TEXT,
                    customer_count INTEGER NOT NULL DEFAULT 0,
                    clv_eur REAL NOT NULL DEFAULT 0,
                    customer_refs TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_campaign_history_created "
                "ON campaign_history(created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_campaign_history_zip "
                "ON campaign_history(zip_code)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(campaign_history)")}
            if "assignments" not in columns:
                conn.execute(
                    "ALTER TABLE campaign_history "
                    "ADD COLUMN assignments TEXT NOT NULL DEFAULT '[]'"
                )
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True
    return path


def _ensure() -> None:
    if not _INITIALIZED:
        init_db()


def insert_campaign(record: dict[str, Any]) -> dict[str, Any]:
    _ensure()
    refs = record.get("customer_refs") or []
    if isinstance(refs, str):
        refs_json = refs
    else:
        refs_json = json.dumps(list(refs))
    assignments = record.get("assignments") or []
    if isinstance(assignments, str):
        assignments_json = assignments
    else:
        assignments_json = json.dumps(list(assignments))
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO campaign_history (
                    campaign_id, zip_code, city, offer_id,
                    customer_count, clv_eur, customer_refs, created_at,
                    assignments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["campaign_id"],
                    str(record["zip_code"]),
                    record.get("city"),
                    record.get("offer_id"),
                    int(record.get("customer_count") or 0),
                    float(record.get("clv_eur") or 0),
                    refs_json,
                    record["created_at"],
                    assignments_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return record


def list_campaigns(*, zip_code: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    _ensure()
    limit = max(1, min(int(limit), 500))
    with _lock:
        conn = _connect()
        try:
            if zip_code:
                rows = conn.execute(
                    """
                    SELECT * FROM campaign_history
                    WHERE zip_code = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (str(zip_code), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM campaign_history
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        finally:
            conn.close()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    refs_raw = row["customer_refs"] or "[]"
    try:
        refs = json.loads(refs_raw)
    except json.JSONDecodeError:
        refs = []
    keys = row.keys()
    assignments_raw = row["assignments"] if "assignments" in keys else "[]"
    try:
        assignments = json.loads(assignments_raw or "[]")
    except json.JSONDecodeError:
        assignments = []
    return {
        "campaign_id": row["campaign_id"],
        "zip_code": row["zip_code"],
        "city": row["city"],
        "offer_id": row["offer_id"],
        "customer_count": row["customer_count"],
        "clv_eur": row["clv_eur"],
        "customer_refs": refs,
        "assignments": assignments,
        "created_at": row["created_at"],
    }


def migrate_from_json(records: list[dict[str, Any]]) -> int:
    """Import legacy campaigns.json rows that are not yet in SQLite."""
    if not records:
        return 0
    existing = {item["campaign_id"] for item in list_campaigns(limit=500)}
    added = 0
    for record in records:
        campaign_id = record.get("campaign_id")
        if not campaign_id or campaign_id in existing:
            continue
        if not record.get("created_at") or not record.get("zip_code"):
            continue
        insert_campaign(record)
        existing.add(campaign_id)
        added += 1
    return added

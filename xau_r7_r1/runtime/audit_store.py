from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import TERMINAL_INTENT_STATES


class StoreError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS = {
    "RESERVED": {"PREFLIGHT_OK", "BLOCKED", "ABANDONED_BEFORE_SEND", "ACKNOWLEDGED", "MANUAL_REVIEW_NO_RESUBMIT", "FAILED_SAFE"},
    "PREFLIGHT_OK": {"DRY_RUN_COMPLETE", "SUBMITTING", "ABANDONED_BEFORE_SEND", "FAILED_SAFE"},
    "SUBMITTING": {"SUBMITTED", "ACKNOWLEDGED", "MANUAL_REVIEW_NO_RESUBMIT", "FAILED_SAFE"},
    "SUBMITTED": {"ACKNOWLEDGED", "MANUAL_REVIEW_NO_RESUBMIT", "FAILED_SAFE"},
}


class AuditStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS order_intents(
                    client_intent_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    broker_ticket INTEGER,
                    last_error TEXT,
                    created_utc REAL NOT NULL,
                    updated_utc REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_state(
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_utc REAL NOT NULL
                );
                """
            )
        except sqlite3.DatabaseError as exc:
            raise StoreError("STATE_DATABASE_OPEN_OR_SCHEMA_FAILED") from exc

    @contextmanager
    def immediate(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    @staticmethod
    def _canon(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _payload_hash(payload_json: str) -> str:
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    def _tail_hash_locked(self) -> str:
        row = self.conn.execute("SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else "0" * 64

    def _append_locked(self, event_type: str, payload: Dict[str, Any]) -> str:
        ts = time.time()
        body = self._canon(payload)
        prev = self._tail_hash_locked()
        digest = hashlib.sha256(f"{prev}|{ts:.6f}|{event_type}|{body}".encode("utf-8")).hexdigest()
        self.conn.execute("INSERT INTO audit_events(ts_utc,event_type,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?)", (ts, event_type, body, prev, digest))
        return digest

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> str:
        with self.immediate():
            return self._append_locked(event_type, payload)

    def reserve_intent(self, client_intent_id: str, payload: Dict[str, Any]) -> bool:
        body = self._canon(payload)
        payload_hash = self._payload_hash(body)
        now = time.time()
        collision = False
        with self.immediate():
            row = self.conn.execute("SELECT payload_hash FROM order_intents WHERE client_intent_id=?", (client_intent_id,)).fetchone()
            if row is not None:
                if row[0] != payload_hash:
                    self._append_locked("INTENT_IDEMPOTENCY_COLLISION", {"client_intent_id": client_intent_id, "existing_payload_hash": row[0], "attempted_payload_hash": payload_hash})
                    collision = True
                else:
                    return False
            else:
                self.conn.execute("INSERT INTO order_intents(client_intent_id,payload_json,payload_hash,state,created_utc,updated_utc) VALUES(?,?,?,?,?,?)", (client_intent_id, body, payload_hash, "RESERVED", now, now))
                self._append_locked("INTENT_RESERVED", {"client_intent_id": client_intent_id, "payload_hash": payload_hash})
        if collision:
            raise StoreError("IDEMPOTENCY_COLLISION")
        return True

    def get_intent(self, client_intent_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT client_intent_id,payload_json,payload_hash,state,broker_ticket,last_error,created_utc,updated_utc FROM order_intents WHERE client_intent_id=?", (client_intent_id,)).fetchone()
        if row is None:
            return None
        return {"client_intent_id": row[0], "payload": json.loads(row[1]), "payload_hash": row[2], "state": row[3], "broker_ticket": row[4], "last_error": row[5], "created_utc": row[6], "updated_utc": row[7]}

    def transition(self, client_intent_id: str, new_state: str, *, broker_ticket: Optional[int] = None, error: Optional[str] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        with self.immediate():
            row = self.conn.execute("SELECT state FROM order_intents WHERE client_intent_id=?", (client_intent_id,)).fetchone()
            if row is None:
                raise StoreError("UNKNOWN_INTENT")
            old_state = row[0]
            if old_state in TERMINAL_INTENT_STATES:
                if old_state == new_state:
                    return
                raise StoreError(f"TERMINAL_STATE_TRANSITION:{old_state}->{new_state}")
            allowed = _ALLOWED_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                raise StoreError(f"ILLEGAL_STATE_TRANSITION:{old_state}->{new_state}")
            self.conn.execute("UPDATE order_intents SET state=?,broker_ticket=COALESCE(?,broker_ticket),last_error=?,updated_utc=? WHERE client_intent_id=?", (new_state, broker_ticket, error, time.time(), client_intent_id))
            payload = {"client_intent_id": client_intent_id, "from": old_state, "to": new_state}
            if broker_ticket is not None:
                payload["broker_ticket"] = broker_ticket
            if error:
                payload["error"] = error
            if detail:
                payload["detail"] = detail
            self._append_locked("INTENT_STATE_TRANSITION", payload)

    def inflight_intents(self) -> List[Dict[str, Any]]:
        placeholders = ",".join("?" for _ in TERMINAL_INTENT_STATES)
        rows = self.conn.execute(f"SELECT client_intent_id FROM order_intents WHERE state NOT IN ({placeholders}) ORDER BY created_utc", tuple(TERMINAL_INTENT_STATES)).fetchall()
        return [self.get_intent(row[0]) for row in rows]

    def set_runtime_state(self, key: str, value: Any) -> None:
        body = self._canon(value)
        with self.immediate():
            self.conn.execute("INSERT INTO runtime_state(key,value_json,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_utc=excluded.updated_utc", (key, body, time.time()))
            self._append_locked("RUNTIME_STATE_SET", {"key": key, "value_sha256": self._payload_hash(body)})

    def get_runtime_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value_json FROM runtime_state WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def verify_chain(self) -> bool:
        prev = "0" * 64
        self.conn.execute("BEGIN")
        try:
            rows = self.conn.execute("SELECT ts_utc,event_type,payload_json,prev_hash,event_hash FROM audit_events ORDER BY seq").fetchall()
            for ts, event_type, payload_json, prev_hash, event_hash in rows:
                if prev_hash != prev:
                    return False
                expected = hashlib.sha256(f"{prev}|{ts:.6f}|{event_type}|{payload_json}".encode("utf-8")).hexdigest()
                if expected != event_hash:
                    return False
                prev = event_hash
            return True
        finally:
            self.conn.execute("ROLLBACK")

    def verify_store_integrity(self) -> Dict[str, Any]:
        """Fail closed if SQLite, audit history, or derived intent state disagree."""
        try:
            quick = self.conn.execute("PRAGMA quick_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise StoreError("STATE_DATABASE_QUICK_CHECK_FAILED") from exc
        if quick != [("ok",)]:
            raise StoreError("STATE_DATABASE_CORRUPT:" + repr(quick[:3]))
        if not self.verify_chain():
            raise StoreError("AUDIT_CHAIN_INTEGRITY_FAILED")

        expected: Dict[str, Dict[str, Any]] = {}
        rows = self.conn.execute("SELECT event_type,payload_json FROM audit_events ORDER BY seq").fetchall()
        for event_type, payload_json in rows:
            try:
                event = json.loads(payload_json)
            except Exception as exc:
                raise StoreError("AUDIT_EVENT_JSON_INVALID") from exc
            if event_type == "INTENT_RESERVED":
                intent_id = event.get("client_intent_id")
                payload_hash = event.get("payload_hash")
                if not isinstance(intent_id, str) or intent_id in expected or not isinstance(payload_hash, str):
                    raise StoreError("INTENT_RESERVATION_LEDGER_INVALID")
                expected[intent_id] = {"state": "RESERVED", "payload_hash": payload_hash, "broker_ticket": None}
            elif event_type == "INTENT_STATE_TRANSITION":
                intent_id = event.get("client_intent_id")
                if intent_id not in expected:
                    raise StoreError("INTENT_TRANSITION_WITHOUT_RESERVATION")
                current = expected[intent_id]["state"]
                old_state = event.get("from")
                new_state = event.get("to")
                if old_state != current:
                    raise StoreError("INTENT_LEDGER_STATE_CONTINUITY_FAILED")
                if current in TERMINAL_INTENT_STATES or new_state not in _ALLOWED_TRANSITIONS.get(current, set()):
                    raise StoreError("INTENT_LEDGER_ILLEGAL_TRANSITION")
                expected[intent_id]["state"] = new_state
                if event.get("broker_ticket") is not None:
                    expected[intent_id]["broker_ticket"] = int(event["broker_ticket"])

        actual_rows = self.conn.execute("SELECT client_intent_id,payload_json,payload_hash,state,broker_ticket FROM order_intents ORDER BY client_intent_id").fetchall()
        actual_ids = {row[0] for row in actual_rows}
        if actual_ids != set(expected):
            raise StoreError("INTENT_TABLE_LEDGER_ID_SET_MISMATCH")
        for intent_id, payload_json, payload_hash, state, broker_ticket in actual_rows:
            if self._payload_hash(payload_json) != payload_hash:
                raise StoreError("INTENT_PAYLOAD_HASH_MISMATCH:" + intent_id)
            exp = expected[intent_id]
            if payload_hash != exp["payload_hash"]:
                raise StoreError("INTENT_PAYLOAD_LEDGER_MISMATCH:" + intent_id)
            if state != exp["state"]:
                raise StoreError("INTENT_STATE_LEDGER_MISMATCH:" + intent_id)
            if exp["broker_ticket"] is not None and broker_ticket != exp["broker_ticket"]:
                raise StoreError("INTENT_BROKER_TICKET_LEDGER_MISMATCH:" + intent_id)

        # Runtime state is not execution authority, but if a value has a matching
        # latest RUNTIME_STATE_SET event, its current bytes must match that hash.
        latest_runtime_hash: Dict[str, str] = {}
        for event_type, payload_json in rows:
            if event_type == "RUNTIME_STATE_SET":
                event = json.loads(payload_json)
                key, digest = event.get("key"), event.get("value_sha256")
                if isinstance(key, str) and isinstance(digest, str):
                    latest_runtime_hash[key] = digest
        for key, value_json in self.conn.execute("SELECT key,value_json FROM runtime_state").fetchall():
            if key in latest_runtime_hash and self._payload_hash(value_json) != latest_runtime_hash[key]:
                raise StoreError("RUNTIME_STATE_LEDGER_MISMATCH:" + key)

        return {"quick_check": "ok", "audit_chain": "PASS", "intent_count": len(actual_rows), "runtime_state_count": len(latest_runtime_hash)}

    def close(self) -> None:
        self.conn.close()

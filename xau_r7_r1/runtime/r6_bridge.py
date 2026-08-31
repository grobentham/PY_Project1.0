from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .execution import ExecutionEngine
from .r6_decision_adapter import DecisionAdapterError, R6DecisionAdapter


MAX_DECISION_FILE_BYTES = 64 * 1024
MANUAL_REVIEW_STATES = {"MANUAL_REVIEW_NO_RESUBMIT"}
REJECTED_STATES = {"BLOCKED", "FAILED_SAFE", "ABANDONED_BEFORE_SEND"}


class BridgeError(RuntimeError):
    pass


class R6InboxProcessor:
    def __init__(self, root: Path, store, gateway, *, execution_enabled: bool = False):
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.processed = self.root / "processed"
        self.rejected = self.root / "rejected"
        self.manual_review = self.root / "manual_review"
        self.pause_marker = self.root / "PAUSED_MANUAL_REVIEW"
        for p in (self.inbox, self.processed, self.rejected, self.manual_review):
            p.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.gateway = gateway
        self.engine = ExecutionEngine(store, gateway, execution_enabled=execution_enabled)
        self.adapter = R6DecisionAdapter()

    @staticmethod
    def _safe_name(path: Path) -> str:
        name = Path(path).name
        if name in {"", ".", ".."}:
            raise BridgeError("INVALID_DECISION_FILENAME")
        return name

    def _archive(self, source: Path, bucket: Path, raw_sha256: str, result: Dict[str, Any]) -> Path:
        bucket.mkdir(parents=True, exist_ok=True)
        stem = Path(source).stem[:80]
        destination = bucket / f"{stem}.{raw_sha256[:16]}.json"
        if destination.exists():
            # Identical evidence may be seen again. Preserve each arrival without overwrite.
            destination = bucket / f"{stem}.{raw_sha256[:16]}.{time.time_ns()}.json"
        os.replace(str(source), str(destination))
        result_path = destination.with_suffix(destination.suffix + ".result.json")
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return destination

    def _write_pause_marker(self, reason: str, decision_file: str) -> None:
        payload = {
            "paused_at_epoch": time.time(),
            "reason": reason,
            "decision_file": decision_file,
            "automatic_resume": False,
        }
        tmp = self.pause_marker.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(self.pause_marker))

    def process_path(self, path: Path, *, now_ms: Optional[int] = None) -> Dict[str, Any]:
        source = Path(path)
        if self.pause_marker.exists():
            raise BridgeError("R6_INBOX_PAUSED_FOR_MANUAL_REVIEW")
        if not source.is_file():
            raise BridgeError("DECISION_FILE_NOT_FOUND")
        if source.suffix.lower() != ".json":
            raise BridgeError("DECISION_FILE_MUST_BE_JSON")
        size = source.stat().st_size
        if size <= 0 or size > MAX_DECISION_FILE_BYTES:
            raise BridgeError("DECISION_FILE_SIZE_INVALID")
        raw = source.read_bytes()
        raw_hash = hashlib.sha256(raw).hexdigest()
        self.store.append_event("R6_DECISION_FILE_SEEN", {
            "file": self._safe_name(source), "raw_sha256": raw_hash, "bytes": len(raw)
        })

        # Parse/validate before any broker call, so malformed decisions cannot
        # consume broker state or be mistaken for executable work.
        try:
            decision, parsed_raw_hash = self.adapter.parse(raw, now_ms=now_ms)
        except Exception as exc:
            result = {"ok": False, "state": "REJECTED_DECISION", "reason": str(exc), "raw_sha256": raw_hash}
            self.store.append_event("R6_DECISION_REJECTED", result)
            archived = self._archive(source, self.rejected, raw_hash, result)
            result["archived_to"] = str(archived)
            return result
        if parsed_raw_hash != raw_hash:
            raise BridgeError("DECISION_HASH_INTERNAL_MISMATCH")

        self.store.append_event("R6_DECISION_VALIDATED", {
            "decision_id": decision.decision_id,
            "source": decision.source,
            "signal_bar_ms": decision.signal_bar_ms,
            "raw_sha256": raw_hash,
        })
        try:
            symbol = self.gateway.symbol_snapshot()
            adapted = self.adapter.adapt(raw, symbol, now_ms=now_ms)
        except Exception as exc:
            result = {"ok": False, "state": "REJECTED_DECISION", "reason": str(exc), "raw_sha256": raw_hash}
            self.store.append_event("R6_DECISION_ADAPTATION_REJECTED", result)
            archived = self._archive(source, self.rejected, raw_hash, result)
            result["archived_to"] = str(archived)
            return result

        self.store.append_event("R6_DECISION_ADAPTED", {
            "decision_id": adapted.decision.decision_id,
            "client_intent_id": adapted.intent.client_intent_id,
            "decision_fingerprint": adapted.decision_fingerprint,
            "raw_sha256": adapted.raw_sha256,
            "source": adapted.decision.source,
            "geometry": adapted.decision.geometry_used,
        })
        try:
            execution_result = self.engine.submit(adapted.intent)
        except Exception as exc:
            # An unexpected exception after adaptation is treated as manual review.
            # We cannot know that no irreversible broker action occurred.
            result = {
                "ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT",
                "reason": "BRIDGE_EXECUTION_EXCEPTION:" + str(exc),
                "raw_sha256": raw_hash,
                "decision_id": adapted.decision.decision_id,
                "client_intent_id": adapted.intent.client_intent_id,
            }
            self.store.append_event("R6_BRIDGE_MANUAL_REVIEW", result)
            archived = self._archive(source, self.manual_review, raw_hash, result)
            self._write_pause_marker(result["reason"], archived.name)
            result["archived_to"] = str(archived)
            return result

        state = execution_result.get("state")
        result = {
            "ok": bool(execution_result.get("ok")),
            "state": state,
            "execution": execution_result,
            "raw_sha256": raw_hash,
            "decision_id": adapted.decision.decision_id,
            "decision_fingerprint": adapted.decision_fingerprint,
            "client_intent_id": adapted.intent.client_intent_id,
        }
        if execution_result.get("duplicate_suppressed"):
            result["state"] = "DUPLICATE_SUPPRESSED"
            bucket = self.processed
        elif state in MANUAL_REVIEW_STATES:
            bucket = self.manual_review
        elif state in REJECTED_STATES:
            bucket = self.rejected
        else:
            bucket = self.processed
        archived = self._archive(source, bucket, raw_hash, result)
        result["archived_to"] = str(archived)
        self.store.append_event("R6_DECISION_ARCHIVED", {
            "decision_id": adapted.decision.decision_id,
            "state": result["state"],
            "raw_sha256": raw_hash,
            "bucket": bucket.name,
        })
        if state in MANUAL_REVIEW_STATES:
            self._write_pause_marker(str(execution_result.get("reason", state)), archived.name)
        return result

    def drain_once(self, *, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.pause_marker.exists():
            raise BridgeError("R6_INBOX_PAUSED_FOR_MANUAL_REVIEW")
        results: List[Dict[str, Any]] = []
        for path in sorted(self.inbox.glob("*.json"), key=lambda p: p.name):
            result = self.process_path(path, now_ms=now_ms)
            results.append(result)
            if result.get("state") == "MANUAL_REVIEW_NO_RESUBMIT":
                break
        return results

    def run_forever(self, *, poll_seconds: float = 0.5) -> None:
        if not (0.1 <= float(poll_seconds) <= 5.0):
            raise BridgeError("INVALID_POLL_SECONDS")
        self.store.append_event("R6_INBOX_LOOP_STARTED", {"poll_seconds": float(poll_seconds)})
        try:
            while True:
                if self.pause_marker.exists():
                    raise BridgeError("R6_INBOX_PAUSED_FOR_MANUAL_REVIEW")
                self.drain_once()
                time.sleep(float(poll_seconds))
        except KeyboardInterrupt:
            self.store.append_event("R6_INBOX_LOOP_STOPPED", {"reason": "KEYBOARD_INTERRUPT"})

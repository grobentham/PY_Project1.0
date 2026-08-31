from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import R6_BRIDGE_PAUSE_STATE_KEY, R6_BRIDGE_RESUME_ACK
from .execution import ExecutionEngine
from .r6_decision_adapter import R6DecisionAdapter

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

    def is_paused(self) -> bool:
        persisted = self.store.get_runtime_state(R6_BRIDGE_PAUSE_STATE_KEY, False)
        return bool(persisted) or self.pause_marker.exists()

    @staticmethod
    def _safe_name(path: Path) -> str:
        name = Path(path).name
        if name in {"", ".", ".."}:
            raise BridgeError("INVALID_DECISION_FILENAME")
        return name

    def _require_inbox_file(self, path: Path) -> Path:
        source = Path(path)
        if source.is_symlink():
            raise BridgeError("DECISION_SYMLINK_NOT_ALLOWED")
        try:
            resolved = source.resolve(strict=True)
            inbox = self.inbox.resolve(strict=True)
        except FileNotFoundError as exc:
            raise BridgeError("DECISION_FILE_NOT_FOUND") from exc
        if resolved.parent != inbox:
            raise BridgeError("DECISION_FILE_MUST_BE_DIRECT_CHILD_OF_INBOX")
        if resolved.suffix.lower() != ".json":
            raise BridgeError("DECISION_FILE_MUST_BE_JSON")
        return resolved

    def _stable_read(self, source: Path) -> bytes:
        before = source.stat()
        if before.st_size <= 0 or before.st_size > MAX_DECISION_FILE_BYTES:
            raise BridgeError("DECISION_FILE_SIZE_INVALID")
        raw = source.read_bytes()
        after = source.stat()
        signature_before = (before.st_size, before.st_mtime_ns)
        signature_after = (after.st_size, after.st_mtime_ns)
        if signature_before != signature_after or len(raw) != after.st_size:
            raise BridgeError("DECISION_FILE_CHANGED_DURING_READ")
        return raw

    def _archive(self, source: Path, bucket: Path, raw_sha256: str, result: Dict[str, Any]) -> Path:
        bucket.mkdir(parents=True, exist_ok=True)
        stem = Path(source).stem[:80]
        destination = bucket / f"{stem}.{raw_sha256[:16]}.json"
        if destination.exists():
            destination = bucket / f"{stem}.{raw_sha256[:16]}.{time.time_ns()}.json"
        os.replace(str(source), str(destination))
        result_path = destination.with_suffix(destination.suffix + ".result.json")
        tmp = result_path.with_suffix(result_path.suffix + ".tmp")
        tmp.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(result_path))
        return destination

    def _write_pause_marker(self, reason: str, decision_file: str) -> None:
        payload = {
            "paused_at_epoch": time.time(),
            "reason": reason,
            "decision_file": decision_file,
            "automatic_resume": False,
        }
        # SQLite is authoritative and is written first. Even if filesystem
        # marker creation/archive subsequently fails, the next operation sees
        # the persistent pause and refuses more decisions.
        self.store.set_runtime_state(R6_BRIDGE_PAUSE_STATE_KEY, payload)
        tmp = self.pause_marker.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(self.pause_marker))

    def clear_pause(self, acknowledgement: str) -> Dict[str, Any]:
        if acknowledgement != R6_BRIDGE_RESUME_ACK:
            raise BridgeError("MANUAL_REVIEW_ACKNOWLEDGEMENT_MISMATCH")
        if not self.is_paused():
            return {"cleared": False, "reason": "NOT_PAUSED"}
        inflight = self.store.inflight_intents()
        if inflight:
            raise BridgeError("CANNOT_RESUME_WITH_INFLIGHT_INTENTS")
        exposure = self.gateway.exposure_snapshot()
        if exposure.total_count != 0 or exposure.total_lot > 1e-12:
            raise BridgeError("CANNOT_RESUME_WITH_XAU_EXPOSURE")
        previous = self.store.get_runtime_state(R6_BRIDGE_PAUSE_STATE_KEY, False)
        self.store.append_event("R6_MANUAL_REVIEW_RESUME_AUTHORIZED", {
            "acknowledgement": acknowledgement,
            "previous_pause": previous,
            "broker_exposure": {
                "position_count": exposure.position_count,
                "pending_order_count": exposure.pending_order_count,
                "total_lot": exposure.total_lot,
            },
        })
        self.store.set_runtime_state(R6_BRIDGE_PAUSE_STATE_KEY, False)
        try:
            self.pause_marker.unlink(missing_ok=True)
        except TypeError:
            if self.pause_marker.exists():
                self.pause_marker.unlink()
        return {"cleared": True, "broker_exposure_zero": True, "automatic_resubmit": False}

    def process_path(self, path: Path, *, now_ms: Optional[int] = None) -> Dict[str, Any]:
        if self.is_paused():
            raise BridgeError("R6_INBOX_PAUSED_FOR_MANUAL_REVIEW")
        source = self._require_inbox_file(path)
        raw = self._stable_read(source)
        raw_hash = hashlib.sha256(raw).hexdigest()
        self.store.append_event("R6_DECISION_FILE_SEEN", {"file": self._safe_name(source), "raw_sha256": raw_hash, "bytes": len(raw)})
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
        self.store.append_event("R6_DECISION_VALIDATED", {"decision_id": decision.decision_id, "source": decision.source, "signal_bar_ms": decision.signal_bar_ms, "raw_sha256": raw_hash})
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
            result = {
                "ok": False,
                "state": "MANUAL_REVIEW_NO_RESUBMIT",
                "reason": "BRIDGE_EXECUTION_EXCEPTION:" + str(exc),
                "raw_sha256": raw_hash,
                "decision_id": adapted.decision.decision_id,
                "client_intent_id": adapted.intent.client_intent_id,
            }
            self.store.append_event("R6_BRIDGE_MANUAL_REVIEW", result)
            # Pause first; archival is secondary evidence handling.
            self._write_pause_marker(result["reason"], self._safe_name(source))
            archived = self._archive(source, self.manual_review, raw_hash, result)
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
        if state in MANUAL_REVIEW_STATES:
            # Persist pause before moving/writing evidence. This prevents an I/O
            # failure from leaving the next inbox item executable.
            self._write_pause_marker(str(execution_result.get("reason", state)), self._safe_name(source))
        archived = self._archive(source, bucket, raw_hash, result)
        result["archived_to"] = str(archived)
        self.store.append_event("R6_DECISION_ARCHIVED", {"decision_id": adapted.decision.decision_id, "state": result["state"], "raw_sha256": raw_hash, "bucket": bucket.name})
        return result

    def drain_once(self, *, now_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.is_paused():
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
                if self.is_paused():
                    raise BridgeError("R6_INBOX_PAUSED_FOR_MANUAL_REVIEW")
                self.drain_once()
                time.sleep(float(poll_seconds))
        except KeyboardInterrupt:
            self.store.append_event("R6_INBOX_LOOP_STOPPED", {"reason": "KEYBOARD_INTERRUPT"})

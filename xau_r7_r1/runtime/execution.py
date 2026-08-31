from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Dict, List

from .audit_store import AuditStore, StoreError
from .models import OrderIntent
from .risk import RiskGovernor


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


class ExecutionError(RuntimeError):
    pass


class ExecutionEngine:
    def __init__(self, store: AuditStore, gateway, *, execution_enabled: bool = False):
        self.store = store
        self.gateway = gateway
        self.execution_enabled = bool(execution_enabled)
        self.risk = RiskGovernor()

    @staticmethod
    def validate_intent_shape(intent: OrderIntent) -> None:
        if not _ID_RE.fullmatch(intent.client_intent_id):
            raise ExecutionError("INVALID_CLIENT_INTENT_ID")
        if intent.side.upper() not in {"BUY", "SELL"}:
            raise ExecutionError("UNSUPPORTED_SIDE")
        if not intent.source or not isinstance(intent.source, str):
            raise ExecutionError("INVALID_SOURCE")

    def _broker_preflight(self, intent: OrderIntent) -> Dict[str, Any]:
        account = self.gateway.account_snapshot()
        symbol = self.gateway.symbol_snapshot()
        exposure = self.gateway.exposure_snapshot()
        entry = self.gateway.current_market_entry(intent.side, symbol)
        self.gateway.validate_broker_geometry(intent, symbol, entry)
        stop_loss_sgd = self.gateway.projected_stop_loss_sgd(intent, entry)
        decision = self.risk.evaluate(
            account=account,
            exposure=exposure,
            intent=intent,
            entry_price=entry,
            projected_stop_loss_sgd=stop_loss_sgd,
        )
        request = self.gateway.build_market_request(intent, entry)
        return {
            "account": asdict(account),
            "symbol": asdict(symbol),
            "exposure": asdict(exposure),
            "decision": asdict(decision),
            "request": request,
        }

    def submit(self, intent: OrderIntent) -> Dict[str, Any]:
        self.validate_intent_shape(intent)
        payload = intent.canonical_payload()
        created = self.store.reserve_intent(intent.client_intent_id, payload)
        if not created:
            existing = self.store.get_intent(intent.client_intent_id)
            self.store.append_event("DUPLICATE_SUBMIT_SUPPRESSED", {"client_intent_id": intent.client_intent_id, "state": existing["state"]})
            return {"ok": False, "duplicate_suppressed": True, "intent": existing}

        try:
            first = self._broker_preflight(intent)
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "BLOCKED", error=str(exc))
            return {"ok": False, "state": "BLOCKED", "reason": str(exc)}

        decision = first["decision"]
        if not decision["allowed"]:
            self.store.transition(
                intent.client_intent_id,
                "BLOCKED",
                error=decision["reason"],
                detail={"risk": decision["risk"]},
            )
            return {"ok": False, "state": "BLOCKED", "reason": decision["reason"], "risk": decision["risk"]}

        try:
            self.gateway.order_check(first["request"])
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "BLOCKED", error=str(exc))
            return {"ok": False, "state": "BLOCKED", "reason": str(exc)}

        self.store.transition(
            intent.client_intent_id,
            "PREFLIGHT_OK",
            detail={"risk": decision["risk"], "entry_price": first["request"]["price"]},
        )

        if not self.execution_enabled:
            self.store.transition(intent.client_intent_id, "DRY_RUN_COMPLETE", detail={"send_attempted": False})
            return {
                "ok": True,
                "state": "DRY_RUN_COMPLETE",
                "send_attempted": False,
                "risk": decision["risk"],
            }

        # Re-snapshot immediately before the irreversible send. A previously valid
        # preflight cannot authorize a changed quote, spread, exposure, or risk state.
        try:
            second = self._broker_preflight(intent)
            second_decision = second["decision"]
            if not second_decision["allowed"]:
                self.store.transition(
                    intent.client_intent_id,
                    "ABANDONED_BEFORE_SEND",
                    error=second_decision["reason"],
                    detail={"risk": second_decision["risk"]},
                )
                return {"ok": False, "state": "ABANDONED_BEFORE_SEND", "reason": second_decision["reason"]}
            self.gateway.order_check(second["request"])
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "ABANDONED_BEFORE_SEND", error=str(exc))
            return {"ok": False, "state": "ABANDONED_BEFORE_SEND", "reason": str(exc)}

        # Persist SUBMITTING before order_send. If the process dies after this point,
        # restart recovery must reconcile with the broker and must never auto-resubmit.
        self.store.transition(intent.client_intent_id, "SUBMITTING", detail={"entry_price": second["request"]["price"]})
        try:
            result = self.gateway.order_send(second["request"])
            ticket = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0) or None
            self.store.transition(intent.client_intent_id, "SUBMITTED", broker_ticket=ticket)
        except Exception as exc:
            match = self.gateway.find_intent_at_broker(intent.client_intent_id)
            if match.found:
                self.store.transition(
                    intent.client_intent_id,
                    "ACKNOWLEDGED",
                    broker_ticket=match.ticket,
                    error=str(exc),
                    detail={"recovered_after_send_exception": True, "broker_kind": match.kind},
                )
                return {"ok": True, "state": "ACKNOWLEDGED", "broker_match": asdict(match)}
            self.store.transition(
                intent.client_intent_id,
                "MANUAL_REVIEW_NO_RESUBMIT",
                error=str(exc),
                detail={"automatic_resubmit": False},
            )
            return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": str(exc)}

        match = self.gateway.find_intent_at_broker(intent.client_intent_id)
        if match.found:
            self.store.transition(
                intent.client_intent_id,
                "ACKNOWLEDGED",
                broker_ticket=match.ticket,
                detail={"broker_kind": match.kind, "broker_state": match.state},
            )
            return {"ok": True, "state": "ACKNOWLEDGED", "broker_match": asdict(match)}

        self.store.transition(
            intent.client_intent_id,
            "MANUAL_REVIEW_NO_RESUBMIT",
            detail={"order_send_returned_success": True, "broker_match_found": False, "automatic_resubmit": False},
        )
        return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": "BROKER_ACK_NOT_RECONCILED"}

    def recover_inflight(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for row in self.store.inflight_intents():
            intent_id = row["client_intent_id"]
            state = row["state"]
            if state in {"RESERVED", "PREFLIGHT_OK"}:
                self.store.transition(intent_id, "ABANDONED_BEFORE_SEND", detail={"restart_recovery": True, "send_was_not_started": True})
                results.append({"client_intent_id": intent_id, "state": "ABANDONED_BEFORE_SEND"})
                continue
            if state in {"SUBMITTING", "SUBMITTED"}:
                match = self.gateway.find_intent_at_broker(intent_id)
                if match.found:
                    self.store.transition(
                        intent_id,
                        "ACKNOWLEDGED",
                        broker_ticket=match.ticket,
                        detail={"restart_recovery": True, "broker_kind": match.kind, "broker_state": match.state},
                    )
                    results.append({"client_intent_id": intent_id, "state": "ACKNOWLEDGED", "broker_match": asdict(match)})
                else:
                    self.store.transition(
                        intent_id,
                        "MANUAL_REVIEW_NO_RESUBMIT",
                        detail={"restart_recovery": True, "automatic_resubmit": False},
                    )
                    results.append({"client_intent_id": intent_id, "state": "MANUAL_REVIEW_NO_RESUBMIT"})
        return results

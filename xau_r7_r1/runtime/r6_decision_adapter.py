from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

from .constants import (
    CANONICAL_R6_ZIP_SHA256,
    MAX_CANONICAL_LOT,
    RETIRED_SOURCE,
    R6_COMPRESSION_GEOMETRY,
    R6_DECISION_ID_MAX_LENGTH,
    R6_DECISION_MAX_AGE_SECONDS,
    R6_DECISION_MAX_FUTURE_SECONDS,
    R6_DECISION_POLICY,
    R6_DECISION_SCHEMA,
    R6_INTENT_ID_HASH_HEX,
    R6_LTM_GEOMETRY,
    R6_SOURCE_FAMILY,
    R6_SOURCE_PRIORITY,
)
from .models import OrderIntent, SymbolSnapshot


class DecisionAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdmittedR6Decision:
    schema: str
    policy: str
    parent_zip_sha256: str
    decision_id: str
    signal_bar_ms: int
    emitted_at_ms: int
    side: int
    source: str
    priority: int
    family: str
    signal_type: str
    atr_usd: float
    stop_atr: float
    target_atr: float
    geometry_used: str
    lot_size: float
    admitted: bool


@dataclass(frozen=True)
class AdaptedDecision:
    decision: AdmittedR6Decision
    intent: OrderIntent
    raw_sha256: str
    derived_entry_price: float


_REQUIRED_FIELDS = {
    "schema",
    "policy",
    "parent_zip_sha256",
    "decision_id",
    "signal_bar_ms",
    "emitted_at_ms",
    "side",
    "source",
    "priority",
    "family",
    "signal_type",
    "atr_usd",
    "stop_atr",
    "target_atr",
    "geometry_used",
    "lot_size",
    "admitted",
}


def _reject_json_constant(token: str):
    raise DecisionAdapterError("DECISION_JSON_NONFINITE_CONSTANT:" + token)


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise DecisionAdapterError(name + "_MUST_BE_NUMERIC_NOT_BOOLEAN")
    try:
        result = float(value)
    except Exception as exc:
        raise DecisionAdapterError(name + "_INVALID_NUMERIC_VALUE") from exc
    if not math.isfinite(result):
        raise DecisionAdapterError(name + "_NONFINITE")
    return result


def _strict_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DecisionAdapterError(name + "_MUST_BE_INTEGER")
    return int(value)


def _require_string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DecisionAdapterError(name + "_MUST_BE_STRING")
    if not allow_empty and not value:
        raise DecisionAdapterError(name + "_EMPTY")
    return value


def _geometry_pair_close(actual_stop: float, actual_target: float, expected: Tuple[float, float]) -> bool:
    return abs(actual_stop - expected[0]) <= 1e-12 and abs(actual_target - expected[1]) <= 1e-12


def _round_price_to_point(value: float, point: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise DecisionAdapterError("DERIVED_PRICE_INVALID")
    if not math.isfinite(point) or point <= 0:
        raise DecisionAdapterError("BROKER_POINT_INVALID")
    d_value = Decimal(str(value))
    d_point = Decimal(str(point))
    units = (d_value / d_point).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(units * d_point)


def _client_intent_id(decision_id: str) -> str:
    digest = hashlib.sha256(decision_id.encode("utf-8")).hexdigest()[:R6_INTENT_ID_HASH_HEX]
    return "r6_" + digest


class R6DecisionAdapter:
    """Translate an already-admitted frozen R6 decision into an OrderIntent.

    This class deliberately does not select signals, models, families, geometry,
    or size. Those decisions must already have been made by the frozen R6
    decision authority. The adapter verifies that frozen output and translates
    ATR geometry onto the current broker market quote.
    """

    def parse(self, raw_bytes: bytes, *, now_ms: Optional[int] = None) -> Tuple[AdmittedR6Decision, str]:
        if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
            raise DecisionAdapterError("DECISION_FILE_EMPTY")
        raw_sha256 = hashlib.sha256(bytes(raw_bytes)).hexdigest()
        try:
            obj = json.loads(bytes(raw_bytes).decode("utf-8-sig"), parse_constant=_reject_json_constant)
        except DecisionAdapterError:
            raise
        except Exception as exc:
            raise DecisionAdapterError("DECISION_JSON_INVALID") from exc
        if not isinstance(obj, dict):
            raise DecisionAdapterError("DECISION_JSON_MUST_BE_OBJECT")
        unknown = set(obj) - _REQUIRED_FIELDS
        missing = _REQUIRED_FIELDS - set(obj)
        if unknown:
            raise DecisionAdapterError("DECISION_UNKNOWN_FIELDS:" + ",".join(sorted(unknown)))
        if missing:
            raise DecisionAdapterError("DECISION_MISSING_FIELDS:" + ",".join(sorted(missing)))

        schema = _require_string(obj["schema"], "DECISION_SCHEMA")
        policy = _require_string(obj["policy"], "DECISION_POLICY")
        parent = _require_string(obj["parent_zip_sha256"], "DECISION_PARENT_HASH")
        decision_id = _require_string(obj["decision_id"], "DECISION_ID")
        source = _require_string(obj["source"], "DECISION_SOURCE")
        family = _require_string(obj["family"], "DECISION_FAMILY", allow_empty=True)
        signal_type = _require_string(obj["signal_type"], "DECISION_SIGNAL_TYPE", allow_empty=True)
        geometry = _require_string(obj["geometry_used"], "DECISION_GEOMETRY")
        signal_bar_ms = _strict_int(obj["signal_bar_ms"], "DECISION_SIGNAL_BAR_MS")
        emitted_at_ms = _strict_int(obj["emitted_at_ms"], "DECISION_EMITTED_AT_MS")
        side = _strict_int(obj["side"], "DECISION_SIDE")
        priority = _strict_int(obj["priority"], "DECISION_PRIORITY")
        atr = _finite_float(obj["atr_usd"], "DECISION_ATR_USD")
        stop_atr = _finite_float(obj["stop_atr"], "DECISION_STOP_ATR")
        target_atr = _finite_float(obj["target_atr"], "DECISION_TARGET_ATR")
        lot = _finite_float(obj["lot_size"], "DECISION_LOT_SIZE")
        admitted = obj["admitted"]
        if not isinstance(admitted, bool):
            raise DecisionAdapterError("DECISION_ADMITTED_MUST_BE_BOOLEAN")

        if schema != R6_DECISION_SCHEMA:
            raise DecisionAdapterError("DECISION_SCHEMA_MISMATCH")
        if policy != R6_DECISION_POLICY:
            raise DecisionAdapterError("DECISION_POLICY_MISMATCH")
        if parent.lower() != CANONICAL_R6_ZIP_SHA256:
            raise DecisionAdapterError("DECISION_PARENT_HASH_MISMATCH")
        if not admitted:
            raise DecisionAdapterError("DECISION_NOT_ADMITTED")
        if len(decision_id) > R6_DECISION_ID_MAX_LENGTH:
            raise DecisionAdapterError("DECISION_ID_TOO_LONG")
        if signal_bar_ms <= 0 or emitted_at_ms <= 0:
            raise DecisionAdapterError("DECISION_TIMESTAMP_NONPOSITIVE")
        if emitted_at_ms < signal_bar_ms:
            raise DecisionAdapterError("DECISION_EMITTED_BEFORE_SIGNAL_BAR")
        if side not in {-1, 1}:
            raise DecisionAdapterError("DECISION_SIDE_MUST_BE_PLUS_OR_MINUS_ONE")
        if atr <= 0 or stop_atr <= 0 or target_atr <= 0:
            raise DecisionAdapterError("DECISION_GEOMETRY_NONPOSITIVE")
        if lot <= 0 or lot > MAX_CANONICAL_LOT + 1e-12:
            raise DecisionAdapterError("DECISION_LOT_OUTSIDE_FROZEN_CEILING")
        if source == RETIRED_SOURCE:
            raise DecisionAdapterError("DECISION_RETIRED_SOURCE_AUX_RF_LTM")
        if source not in R6_SOURCE_PRIORITY:
            raise DecisionAdapterError("DECISION_SOURCE_NOT_FROZEN_R6")
        if priority != R6_SOURCE_PRIORITY[source]:
            raise DecisionAdapterError("DECISION_SOURCE_PRIORITY_MISMATCH")

        if source in R6_SOURCE_FAMILY:
            if family != R6_SOURCE_FAMILY[source]:
                raise DecisionAdapterError("DECISION_SOURCE_FAMILY_MISMATCH")
        elif source == "CORE":
            # Protected validation carries an empty family on CORE rows. A live
            # producer may also explicitly label it BASE, but must identify the
            # exact signal type and may not invent a lane family.
            if family not in {"", "BASE"}:
                raise DecisionAdapterError("DECISION_CORE_FAMILY_INVALID")
            if not signal_type:
                raise DecisionAdapterError("DECISION_CORE_SIGNAL_TYPE_REQUIRED")
        else:  # defensive: source allow-list above should make this unreachable
            raise DecisionAdapterError("DECISION_SOURCE_UNHANDLED")

        if source in {"TIME_LANE", "ADAPTIVE_LTM_RIDGE"}:
            expected = R6_LTM_GEOMETRY.get(geometry)
            if expected is None or not _geometry_pair_close(stop_atr, target_atr, expected):
                raise DecisionAdapterError("DECISION_LTM_GEOMETRY_MISMATCH")
            if signal_type not in {"", "LIQUIDITY_TRANSITION_MOMENTUM"}:
                raise DecisionAdapterError("DECISION_LTM_SIGNAL_TYPE_MISMATCH")
        elif source in {"COMPRESSION_LANE", "AUX_COMP_RF"}:
            expected = R6_COMPRESSION_GEOMETRY.get(geometry)
            if expected is None or not _geometry_pair_close(stop_atr, target_atr, expected):
                raise DecisionAdapterError("DECISION_COMPRESSION_GEOMETRY_MISMATCH")
            if signal_type not in {"", "COMPRESSION_EXPANSION_BREAKOUT"}:
                raise DecisionAdapterError("DECISION_COMPRESSION_SIGNAL_TYPE_MISMATCH")
        elif source == "CORE":
            if geometry != "PRIMARY":
                raise DecisionAdapterError("DECISION_CORE_GEOMETRY_MUST_BE_PRIMARY")
            # CORE geometry is signal-specific in frozen validation. Do not
            # infer or overwrite the selected positive finite stop/target pair.

        now = int(time.time() * 1000) if now_ms is None else _strict_int(now_ms, "DECISION_NOW_MS")
        age_ms = now - emitted_at_ms
        if age_ms < -int(R6_DECISION_MAX_FUTURE_SECONDS * 1000):
            raise DecisionAdapterError("DECISION_TIMESTAMP_TOO_FAR_IN_FUTURE")
        if age_ms > int(R6_DECISION_MAX_AGE_SECONDS * 1000):
            raise DecisionAdapterError("DECISION_STALE")

        decision = AdmittedR6Decision(
            schema=schema,
            policy=policy,
            parent_zip_sha256=parent.lower(),
            decision_id=decision_id,
            signal_bar_ms=signal_bar_ms,
            emitted_at_ms=emitted_at_ms,
            side=side,
            source=source,
            priority=priority,
            family=family,
            signal_type=signal_type,
            atr_usd=atr,
            stop_atr=stop_atr,
            target_atr=target_atr,
            geometry_used=geometry,
            lot_size=lot,
            admitted=admitted,
        )
        return decision, raw_sha256

    def adapt(self, raw_bytes: bytes, symbol: SymbolSnapshot, *, now_ms: Optional[int] = None) -> AdaptedDecision:
        decision, raw_sha256 = self.parse(raw_bytes, now_ms=now_ms)
        if not math.isfinite(symbol.point) or symbol.point <= 0:
            raise DecisionAdapterError("BROKER_POINT_INVALID")
        entry = float(symbol.ask if decision.side == 1 else symbol.bid)
        if not math.isfinite(entry) or entry <= 0:
            raise DecisionAdapterError("BROKER_ENTRY_PRICE_INVALID")

        if decision.side == 1:
            stop = entry - decision.stop_atr * decision.atr_usd
            target = entry + decision.target_atr * decision.atr_usd
            side = "BUY"
        else:
            stop = entry + decision.stop_atr * decision.atr_usd
            target = entry - decision.target_atr * decision.atr_usd
            side = "SELL"

        stop = _round_price_to_point(stop, symbol.point)
        target = _round_price_to_point(target, symbol.point)
        if side == "BUY" and not (stop < entry < target):
            raise DecisionAdapterError("DERIVED_LONG_GEOMETRY_INVALID")
        if side == "SELL" and not (target < entry < stop):
            raise DecisionAdapterError("DERIVED_SHORT_GEOMETRY_INVALID")

        intent = OrderIntent(
            client_intent_id=_client_intent_id(decision.decision_id),
            side=side,
            lot=decision.lot_size,
            stop_price=stop,
            take_profit_price=target,
            source=decision.source,
        )
        return AdaptedDecision(
            decision=decision,
            intent=intent,
            raw_sha256=raw_sha256,
            derived_entry_price=entry,
        )

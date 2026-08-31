# V16 R7-R1 Full Runtime Repair Audit

## Purpose

R7-R1 is a replacement operational-runtime repair built around the exact canonical frozen R6 package. It is not a strategy promotion, does not retune R6, and does not read Final Holdout outcomes.

Canonical parent:

- `XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`
- SHA-256 `8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

## Closed software defects

| Area | R7-R1 repair |
|---|---|
| Parent identity | Builder pins the exact canonical R6 ZIP SHA-256 and refuses any mismatch. |
| Strategy preservation | Builder hashes the entire inherited parent tree and protected R6 strategy/policy files; inherited files remain byte-identical except the intentional root launcher replacement. |
| Runtime integrity | Runtime Python files and replacement launcher are hashed in the package manifest and checked before mutable runtime state is opened. |
| Persistent state | SQLite WAL + `synchronous=FULL`, transactional writes, append-only hash-chained audit ledger, semantic state replay, exact intent-table reconciliation, exact broker-ticket replay and exact audited runtime-state key/value reconciliation. |
| Deleted/injected state | Deleting an audited pause row, injecting unaudited runtime state, deleting/injecting intents, changing payload/state/tickets, or breaking the audit chain fails closed. |
| Risk governor wiring | Every executable decision passes broker-derived preflight risk before `order_check` and again immediately before `order_send`. |
| Projected risk source | Caller cannot provide projected loss. MT5 `order_calc_profit()` plus frozen commission assumptions are used. Pre-send risk budgets the configured adverse deviation. |
| Actual-fill risk | A position is ACKed only after actual broker fill side, volume, SL, TP, submitted protection and stop-risk are verified. Unsafe actual fills trigger scoped containment. |
| Partial/asynchronous fills | `PLACED` and `DONE_PARTIAL` are never ACKed. They enter containment + `MANUAL_REVIEW_NO_RESUBMIT`. |
| Broker protection mutation | Immediate fills must preserve the submitted rounded SL/TP; altered/missing protection is contained rather than accepted. |
| Duplicate orders | Local payload-hash idempotency plus broker magic/comment reconciliation. |
| Crash recovery | `RESERVED`/`PREFLIGHT_OK` are abandoned before send; `SUBMITTING`/`SUBMITTED` reconcile against broker state and never auto-resubmit. Reconciliation failures attempt owned-exposure containment before terminal manual review. |
| Post-send ambiguity | Missing ACK, unstable DEAL-only state, pending remainder, exposure mismatch, risk breach, query failure or containment failure all force `MANUAL_REVIEW_NO_RESUBMIT`. |
| Emergency containment | Cancels/closes only the R7-R1-owned intent identified by R7 magic/comment. It does not touch unrelated XAU positions. Normal entry spread limits cannot prevent an emergency exit. Residual exposure is reported and never treated as safe. |
| Manual-review pause | Pause is persisted in SQLite before evidence archival and mirrored to filesystem. Deleting only the marker cannot resume. Explicit resume requires exact acknowledgement, zero XAU exposure and zero in-flight intents. |
| Account switching | Connected login/server are pinned and revalidated on sensitive broker reads; account/server switching fails closed. |
| Broker permissions | Demo trade mode, Blueberry server identity, SGD currency, terminal connectivity, Python trade API, Expert trading, symbol trade mode, market/SL/TP permissions and symbol availability are checked. |
| Exposure domain | Every current `XAUUSD.i` position and pending order is counted regardless of magic before a new position may be admitted. |
| Raw-order bypass | Raw/manual JSON has diagnostic preflight capability only and no send authority. Actual send authority is created only by the frozen-R6 admitted-decision adapter. |
| Operator bypass | Single launcher exposes status, recovery, no-send diagnostic preflight, frozen-R6 decision inbox controls and explicit pause resume. The executable legacy-launcher bypass was removed. Original R6 launcher bytes remain evidence only. |
| Decision replay | Both decision emission time and the underlying R6 signal timestamp have independent freshness limits; a stale signal cannot be revived with a fresh emission timestamp. |
| Inbox safety | Direct-child-only JSON ingestion, no symlinks, size cap, stable-read check, SHA-256 evidence, quarantine/archive buckets and duplicate suppression. |
| Build verification | Builder compiles and runs the offline regression suite before packaging and again after clean ZIP extraction, then verifies inherited/runtime hashes. |
| Python compatibility | GitHub Actions runs the builder-equivalent runtime/tests on Python 3.9, 3.11 and 3.13. |

## Frozen policy retained

- R6 strategy logic: unchanged.
- `AUX_RF_LTM`: retired.
- Operating projected-stop risk cap: 0.55%.
- Constitutional projected-stop risk ceiling: 0.60%.
- Projected-equity floor: S$850.
- Maximum canonical lot: 0.02.
- One XAU exposure domain at a time.
- Martingale: OFF.
- Recovery: OFF.
- Averaging down: OFF.
- Pyramiding: OFF.
- Loss-contingent sizing: OFF.
- Final Holdout access: NO.
- Strategy retuning: NONE.

## Execution lock

Order sending is disabled by default and remains demo-only. Automatic R6 decision consumption requires both:

1. `R7_R1_RUNTIME_CONFIG.json` -> `"request_demo_execution": true`
2. `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

Even with those two switches, raw/manual intents cannot send. Only an intent constructed by the strict frozen-R6 admitted-decision adapter carries the internal execution authority accepted by `ExecutionEngine`.

## Important remaining architecture boundary

The operational broker/risk/state/containment layer is repaired, but R7-R1 still does **not** claim that the frozen research/backtest code has magically become a causal live signal generator.

The automatic inbox accepts a strict already-admitted R6 decision contract. It verifies policy identity, parent hash, source/priority/family, selected frozen geometry, lot ceiling, timestamps, freshness and idempotency, but those checks do not prove that the upstream feature calculations and signal-selection logic were produced by an exact causal live implementation of frozen R6.

Therefore the next software phase is an exact **R6 decision producer** derived from the frozen R6 feature/selector source itself. It must emit the admitted-decision contract without reconstructing or retuning strategy logic from outcome/validation rows.

Until that producer exists and is audited, R7-R1 is a hardened demo execution runtime and decision-consumer boundary, not a complete autonomous strategy system.

## Verification status

The hardened runtime branch has passed the builder-equivalent compile/regression workflow on Python 3.9, 3.11 and 3.13 after the containment/state-integrity repairs. The release ZIP still must be produced by `BUILD_R7_R1.ps1` against the exact canonical R6 ZIP and pass its clean-extraction verification before a package can be called release-built.

## Release rule

Do not call the package `SEALED`, `FINAL`, production-ready, or live-ready merely because the runtime tests pass. Real/live-account execution remains prohibited. The autonomous system remains incomplete until the exact frozen-R6 causal decision producer is implemented and audited.

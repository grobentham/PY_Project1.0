# XAU V16 R7-R1 — Full Runtime Repair

## Status

R7-R1 is a hardened operational runtime around the frozen V16 R6 strategy package.

The **runtime repair scope is closed**: the adversarial repair audit has no known open Critical/High/Medium runtime defect. The runtime/test tree is verified on Linux Python 3.9/3.11/3.13 and Windows Python 3.11, including PowerShell builder parsing and the Windows single-instance-lock path.

It does **not** retune R6 and does **not** access Final Holdout outcomes. Real/live account execution is prohibited.

Most importantly, packaged R7-R1 order sending is currently **hard-locked even on demo** because the exact causal frozen-R6 decision producer has not yet been implemented and audited. This prevents hand-crafted JSON from masquerading as genuine R6 strategy output.

## Requirements

- Windows 10/11
- Python 3.9 or newer
- MetaTrader 5 desktop terminal for connected status/recovery
- Blueberry Markets demo account
- account currency SGD
- broker symbol `XAUUSD.i`
- Python package `MetaTrader5` for connected MT5 operations

Offline software/integrity status does not require MetaTrader 5 connectivity.

## Start

Run only:

`START_XAU.bat`

The launcher provides:

1. Offline package + persistent-state integrity status
2. MT5 account/quote/exposure status
3. Crash-recovery reconciliation — never auto-resends
4. Raw-intent diagnostic preflight — no send authority and ephemeral state only
5. Open the R6 decision inbox for staging only
6. Producer/execution readiness status
7. Explicit manual-review pause clearing after broker review
0. Exit

There is no raw-order send option and no executable legacy R6 launcher option.

## Frozen risk enforcement

The execution engine enforces:

- 0.55% operating projected-stop risk cap
- 0.60% constitutional projected-stop risk ceiling
- S$850 projected-equity floor
- maximum 0.02 canonical lot
- one `XAUUSD.i` exposure domain at a time, including pending orders
- permanent `AUX_RF_LTM` rejection
- martingale OFF
- recovery OFF
- averaging down OFF
- pyramiding OFF
- loss-contingent sizing OFF

Pre-send projected stop risk comes from MT5 `order_calc_profit()` plus the frozen commission assumption and an adverse execution-deviation budget. The caller cannot supply its own projected-loss number.

After a broker fill, ACK requires actual side, actual full lot, SL, TP, submitted protective-price preservation and actual stop-risk verification. `PLACED` and `DONE_PARTIAL` are never ACKed. Unsafe or ambiguous owned exposure enters scoped emergency containment and `MANUAL_REVIEW_NO_RESUBMIT`.

## Persistent-state safety

SQLite is configured with WAL and `synchronous=FULL`. Runtime state and intent state are checked against the append-only hash-chained audit ledger before MT5 is touched.

The integrity gate detects, among other things:

- deleted or injected intents
- payload or state mutation
- injected/changed broker tickets
- deleted audited runtime-state rows
- injected unaudited runtime-state rows
- runtime-state value mutation
- audit-chain mutation

Manual-review pause is persisted to SQLite before evidence archival and mirrored to the filesystem. Deleting only the marker does not resume operation. Resume requires the exact acknowledgement phrase, zero XAU exposure and zero unresolved in-flight intents.

Raw diagnostic preflight is isolated from this persistent state. It runs against a temporary SQLite database and cannot reserve IDs or write events into the operational idempotency ledger.

## Broker safety

Connected account/server identity is pinned and rechecked on sensitive operations. The gateway rejects non-SGD accounts, non-Blueberry servers, non-demo trade mode, account/server switching, invalid/stale quotes, excessive entry spread, invalid volume/stops geometry and disabled terminal/account/symbol trading permissions.

Emergency containment is scoped to R7-R1-owned magic/comment exposure only. It does not touch unrelated XAU positions. Normal entry spread restrictions do not prevent an emergency close attempt.

## Frozen-R6 decision boundary

The runtime contains a strict admitted-decision parser for the eventual causal R6 producer. It checks:

- frozen schema and policy ID
- exact canonical R6 parent SHA-256
- admitted flag
- source / priority / family mapping
- frozen source-specific geometry
- canonical lot ceiling
- emission freshness
- independent underlying signal freshness
- retired `AUX_RF_LTM`
- idempotent decision fingerprint

That parser proves the decision **shape and frozen constraints**, not how the upstream signal was calculated. Therefore a manually created JSON is not sufficient provenance for autonomous execution.

## Causal-producer readiness lock

`CAUSAL_R6_PRODUCER_READY` is hard-coded `False` in R7-R1 and the current package manifest is required to attest the same value. Consequently, the packaged runtime cannot reach automatic decision sending even if both demo unlock inputs are set.

A future audited successor may enable the runtime only after it contains an exact causal producer derived from the frozen R6 feature/selector source.

The existing two demo unlock inputs are retained as additional gates for that successor:

1. `R7_R1_RUNTIME_CONFIG.json` -> `"request_demo_execution": true`
2. `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

They are necessary but **not sufficient** in R7-R1.

## Crash and duplicate behavior

- Intent payloads are transactional and idempotent.
- Changed payload under the same intent ID fails closed.
- Broker magic/comment is checked for duplicates.
- `SUBMITTING` is persisted before `order_send()`.
- Restart recovery reconciles in-flight state and never auto-resubmits.
- Reconciliation failures after a possible send attempt scoped containment before terminal manual review.

## Integrity and build behavior

Every packaged invocation verifies the recorded inherited R6 and R7 runtime hashes before mutable state is used. `BUILD_R7_R1.ps1` also compiles, unit-tests and integrity-checks the assembled package before ZIP creation and repeats those checks after clean extraction before reporting PASS.

R7-R1 should be described as a **repaired hardened fail-closed runtime**. It is not yet a complete autonomous R6 trading system because the exact causal decision producer remains the next implementation phase.

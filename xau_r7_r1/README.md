# XAU V16 R7-R1 — Full Runtime Repair

R7-R1 is the hardened operational-runtime successor around the exact canonical frozen R6 package. It does not retune strategy logic and does not read Final Holdout outcomes.

## Canonical parent

`XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`

Required SHA-256:

`8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

The builder refuses any different parent digest.

## What the repaired runtime now does

- Verifies the canonical parent and inherited R6 files.
- Preserves protected R6 strategy/policy bytes.
- Uses SQLite WAL + `synchronous=FULL` state and a hash-chained audit ledger.
- Replays persistent state against the audit ledger before any MT5 call.
- Enforces idempotent decision/order intent handling and crash recovery with no automatic resend of ambiguous orders.
- Pins the connected Blueberry demo account/server and rejects account switching.
- Requires SGD, `XAUUSD.i`, demo trade mode and valid MT5 terminal/account/symbol trading permissions.
- Counts all `XAUUSD.i` positions and pending orders before admitting new exposure.
- Derives pre-send stop risk from MT5 and budgets adverse execution deviation.
- Enforces the frozen 0.55% operating cap, 0.60% constitutional ceiling, S$850 projected-equity floor, 0.02 lot maximum and permanent `AUX_RF_LTM` retirement.
- Keeps martingale, recovery, averaging down, pyramiding and loss-contingent sizing disabled.
- Reprices only the already-selected frozen ATR geometry at each broker preflight; it does not re-select strategy logic.
- Verifies actual filled side, lot, SL, TP and actual stop risk before ACK.
- Never ACKs `PLACED` or `DONE_PARTIAL` market-send outcomes.
- Contains unsafe/ambiguous R7-owned exposure and enters persistent manual-review state rather than resubmitting.
- Persists manual-review pause before evidence archival; explicit resume requires zero XAU exposure, zero in-flight intents and the exact acknowledgement phrase.
- Accepts automatic execution only through the strict admitted-R6 decision contract. Raw/manual intents are diagnostic-only and cannot send.
- Rejects stale decision emissions and independently rejects stale underlying R6 signal timestamps.
- Uses a single operator launcher generated as `START_XAU.bat`.
- Keeps real/live account execution prohibited.

## Demo execution lock

Automatic admitted-R6 decision execution remains OFF unless both are present:

1. `R7_R1_RUNTIME_CONFIG.json` contains `"request_demo_execution": true`
2. environment variable `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

These switches do not authorize raw/manual intents. They only enable the frozen-R6 decision inbox path on a validated Blueberry demo account.

## Decision inbox

The runtime creates `r7_r6_bridge/inbox`. A decision must be a direct-child JSON file and must pass the strict frozen-R6 schema/policy/parent/source/geometry/lot/timestamp checks before it can become an executable intent. Files are hashed and moved to processed, rejected or manual-review evidence buckets.

Any ambiguous post-send state stops automatic consumption and persists a manual-review pause.

## Important remaining boundary

The broker/risk/state/containment runtime is repaired. The remaining autonomous-system gap is the **exact causal R6 decision producer**.

R7-R1 deliberately does not manufacture a live strategy by copying validation rows or approximating the frozen research selector. The current inbox consumes an already-admitted R6 decision and validates its contract; it does not prove how the upstream decision was calculated.

The next software phase is therefore to derive a causal decision producer from the exact frozen R6 feature/selector source, keeping the frozen policy unchanged, and have that producer emit the admitted-decision contract directly into the hardened runtime.

## Build

`BUILD_R7_R1.ps1` requires the exact canonical R6 ZIP beside the script. It compiles and tests the runtime before packaging, generates integrity manifests, creates the R7-R1 ZIP, extracts it into a clean directory, reruns compile/tests/offline integrity checks, verifies hashes and writes a SHA-256 sidecar.

Do not call the autonomous trading system production-ready or live-ready until the exact causal producer is implemented and separately audited. Live accounts remain prohibited by this runtime regardless.

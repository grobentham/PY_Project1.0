# XAU V16 R7-R1 — Full Runtime Repair

R7-R1 is the hardened operational-runtime successor around the exact canonical frozen R6 package. It does not retune strategy logic and does not read Final Holdout outcomes.

## Canonical parent

`XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`

Required SHA-256:

`8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

The builder refuses any different parent digest.

## Repair status

The R7-R1 **hardened runtime repair scope is closed**: no known Critical/High/Medium runtime repair defect remains from the adversarial audit. The current runtime/test tree is verified on Linux Python 3.9/3.11/3.13 and Windows Python 3.11; the Windows lane also parses the PowerShell builder and exercises the Windows single-instance-lock implementation.

This does not mean autonomous R6 trading is complete. The exact causal frozen-R6 decision producer is a separate implementation phase and remains hard-locked out of execution.

## What the repaired runtime now does

- Verifies the canonical parent and inherited R6 files.
- Preserves protected R6 strategy/policy bytes.
- Uses SQLite WAL + `synchronous=FULL` state and a hash-chained audit ledger.
- Replays persistent state against the audit ledger before any MT5 call.
- Enforces idempotent decision/order handling and crash recovery with no automatic resend of ambiguous orders.
- Pins the connected Blueberry demo account/server and rejects account switching.
- Requires SGD, `XAUUSD.i`, demo trade mode and valid MT5 terminal/account/symbol trading permissions.
- Counts all `XAUUSD.i` positions and pending orders before admitting exposure.
- Derives pre-send stop risk from MT5 and budgets adverse execution deviation.
- Enforces the frozen 0.55% operating cap, 0.60% constitutional ceiling, S$850 projected-equity floor, 0.02 lot maximum and permanent `AUX_RF_LTM` retirement.
- Keeps martingale, recovery, averaging down, pyramiding and loss-contingent sizing disabled.
- Reprices only an already-selected frozen ATR geometry at broker preflight; it does not re-select strategy logic.
- Verifies actual filled side, lot, SL, TP and actual stop risk before ACK.
- Never ACKs `PLACED` or `DONE_PARTIAL` market-send outcomes.
- Contains unsafe/ambiguous R7-owned exposure and enters persistent manual review instead of resubmitting.
- Persists manual-review pause before evidence archival; explicit resume requires zero XAU exposure, zero in-flight intents and the exact acknowledgement phrase.
- Gives raw/manual intents diagnostic preflight only; diagnostics use an ephemeral SQLite store and cannot contaminate the operational idempotency ledger.
- Rejects stale decision emissions and independently rejects stale underlying R6 signal timestamps.
- Uses a single operator launcher generated as `START_XAU.bat`.
- Keeps real/live-account execution prohibited.

## Execution lock

`CAUSAL_R6_PRODUCER_READY = False` is hard-coded and is also required by the current package-integrity manifest. Therefore **automatic admitted-R6 decision execution is disabled even on demo**.

The two operator demo switches remain only as additional future gates:

1. `R7_R1_RUNTIME_CONFIG.json` contains `"request_demo_execution": true`
2. environment variable `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

They are not sufficient in R7-R1. Automatic execution cannot unlock until an exact causal R6 producer is implemented, audited and explicitly admitted in a successor.

Raw/manual intents never receive send authority.

## Decision inbox

The runtime may create `r7_r6_bridge/inbox` for **staging only**. The strict parser can verify an already-admitted decision's schema/policy/parent/source/geometry/lot/timestamps/freshness/idempotency, but R7-R1 will refuse automatic inbox processing while the causal-producer readiness lock is false.

This prevents a hand-written JSON file from masquerading as genuine frozen-R6 strategy output.

## Important remaining boundary

The broker/risk/state/containment runtime is repaired. The remaining autonomous-system gap is the **exact causal R6 decision producer**.

R7-R1 deliberately does not manufacture a live strategy by copying validation rows or approximating the frozen research selector. The producer must be derived from the exact canonical frozen R5/R6 feature and selector source while keeping the policy unchanged.

That is a new implementation phase, not an unresolved bypass in the repaired runtime.

## Build

`BUILD_R7_R1.ps1` requires the exact canonical R6 ZIP beside the script. It compiles and tests the runtime before packaging, generates integrity manifests, creates the R7-R1 ZIP, extracts it into a clean directory, reruns compile/tests/offline integrity checks, verifies hashes and writes a SHA-256 sidecar.

Do not call the autonomous trading system production-ready, live-ready, `SEALED` or `FINAL` until the exact causal producer is implemented and separately audited and the fused package is successfully built/certified. Live accounts remain prohibited.

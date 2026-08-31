# XAU V16 R7-R1 — Full Runtime Repair

R7-R1 is the hardened operational-runtime successor around the exact canonical frozen R6 package. It does not retune strategy logic and does not read Final Holdout outcomes.

## Canonical parent

`XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`

Required SHA-256:

`8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

The builder and source-extraction tools refuse any different parent digest.

## Repair status

The R7-R1 **hardened runtime repair scope is closed**: no known Critical/High/Medium broker/risk/state/containment defect remains from the adversarial repair program. The current runtime/test tree is exercised on Linux Python 3.9/3.11/3.13 and Windows Python 3.11.

The causal-producer phase is now substantially hardened too, but the actual source-derived `r6_causal_producer.py` has not yet been admitted. Automatic R6 trading therefore remains hard-locked.

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

## Causal-producer integrity chain

The producer phase now has an explicit fail-closed chain rather than a Boolean readiness claim:

1. `EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1` verifies the canonical R6 ZIP and invokes source-bundle V3.
2. `r6_source_bundle.py` extracts only the frozen Python entry source plus its recursively resolved archive-local Python dependency closure. Relative/local dependencies are mandatory; missing local code, dynamic imports, symlinks, unsafe paths, duplicates and size-limit violations fail closed. Non-archive imports are recorded for environment review instead of being silently treated as local source.
3. `r6_source_probe.py` V2 AST-maps the frozen entry engines without importing or executing them. It records normalized function source, AST hashes, source spans, call dependencies, referenced names, constants and top-level assignment expressions.
4. `r6_producer_parity.py` V2 builds machine-derived parity evidence from causal-prefix reference/producer streams and binds that evidence to the exact source-probe hash, source-bundle-manifest hash, producer-module hash, stream hashes and isolation-manifest hash.
5. `r6_producer_admission.py` V3 independently checks every source-closure file against both the source-bundle manifest and the canonical parent-tree hashes, rejects research/Final-Holdout source paths, verifies the deep source probe, verifies zero-mismatch causal parity and rejects `AUX_RF_LTM` emission/coverage.
6. `r6_producer_seal.py` and `SEAL_R6_PRODUCER_CANDIDATE.ps1` validate a complete candidate only in a temporary copy of an extracted R7-R1 baseline. Candidate sealing cannot mutate protected R6 bytes, cannot flip the readiness switch and cannot unlock execution. Resealing safely ignores only the prior generated seal file.

The exact candidate layout accepted by the sealing layer is deliberately narrow:

- `r7_runtime/r6_causal_producer.py`
- `R7_R1_R6_SOURCE_PROBE.json`
- `R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json`
- `R7_R1_R6_REFERENCE_STREAM.jsonl`
- `R7_R1_R6_PRODUCER_STREAM.jsonl`
- `R7_R1_R6_PARITY_ISOLATION.json`
- `R7_R1_R6_PRODUCER_PARITY.json`

Unexpected candidate files are rejected. A generated `R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json` may exist from a previous seal and is ignored for repeatability, but it is never treated as producer evidence.

## Execution lock

`CAUSAL_R6_PRODUCER_READY = False` is hard-coded and is also required by the current package-integrity manifest. Therefore **automatic admitted-R6 decision execution is disabled even on demo**.

The two operator demo switches remain only as additional future gates:

1. `R7_R1_RUNTIME_CONFIG.json` contains `"request_demo_execution": true`
2. environment variable `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

They are not sufficient in R7-R1. Even a future readiness flip cannot unlock execution unless the runtime producer-admission evidence also verifies at startup.

Raw/manual intents never receive send authority.

## Decision inbox

The runtime may create `r7_r6_bridge/inbox` for **staging only**. The strict parser can verify an already-admitted decision's schema/policy/parent/source/geometry/lot/timestamps/freshness/idempotency, but R7-R1 refuses automatic inbox processing while the causal-producer readiness lock is false.

This prevents a hand-written JSON file from masquerading as genuine frozen-R6 strategy output.

## Important remaining boundary

The remaining autonomous-system gap is the **actual exact causal R6 decision producer implementation**.

R7-R1 deliberately does not manufacture that producer by copying validation rows, reading outcome columns, approximating the frozen selector or using Final Holdout data. The producer must be implemented from the canonical frozen source/dependency map and then pass the hash-bound causal parity/admission/sealing chain above.

The canonical archive has been recovered in the project workflow, but the current local command/Python execution backend has not been able to start a process to extract its member source inside this ChatGPT runtime. That tooling limitation does not weaken the admission rules and is not treated as permission to reconstruct the strategy from outcomes.

## Build

`BUILD_R7_R1.ps1` requires the exact canonical R6 ZIP beside the script. It compiles and tests the runtime before packaging, generates integrity manifests, creates the R7-R1 ZIP, extracts it into a clean directory, reruns compile/tests/offline integrity checks, verifies hashes and writes a SHA-256 sidecar.

The current builder intentionally emits a producer-locked baseline. A successfully sealed producer candidate is evidence for a later explicit fused-release step; candidate sealing itself never changes the baseline's `causal_r6_producer_ready = false` constitutional state.

Do not call the autonomous trading system production-ready, live-ready, `SEALED` or `FINAL` until the exact causal producer is implemented and separately audited and a fused package is successfully built/certified. Live accounts remain prohibited.

# XAU V16 R7-R1 — Full Runtime Repair

R7-R1 is the hardened operational-runtime successor around the exact canonical frozen R6 package. It does not retune strategy logic and does not read Final Holdout outcomes.

## Canonical parent

`XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`

Required SHA-256:

`8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

The release builder and source-extraction tools refuse any different parent digest.

## Repair status

The R7-R1 hardened broker/risk/state/containment repair has no known open Critical/High/Medium defect from the current adversarial repair program. The runtime/test tree is exercised on Linux Python 3.9/3.11/3.13 and Windows Python 3.11.

The producer-verification infrastructure is also fail-closed and version-pinned, but the exact source-derived causal `r6_causal_producer.py` and exact canonical-reference executor have not yet been implemented/admitted from frozen R6 source. Automatic R6 order execution therefore remains hard-locked.

## What the repaired runtime does

- Verifies exact canonical-parent identity and inherited R6 files.
- Preserves protected R6 strategy/policy bytes.
- Uses SQLite WAL + `synchronous=FULL` state and a hash-chained audit ledger.
- Replays persistent state against the audit ledger before any MT5 call.
- Enforces idempotent decision/order handling and crash recovery with no automatic resend of ambiguous orders.
- Pins the connected Blueberry demo account/server and rejects identity switching.
- Requires SGD, `XAUUSD.i`, demo trade mode and valid MT5 terminal/account/symbol trading permissions.
- Counts all `XAUUSD.i` positions and pending orders before admitting exposure.
- Derives pre-send stop risk from MT5 and budgets adverse execution deviation.
- Enforces the frozen 0.55% operating cap, 0.60% constitutional ceiling, S$850 projected-equity floor, 0.02 lot maximum and permanent `AUX_RF_LTM` retirement.
- Keeps martingale, recovery, averaging down, pyramiding and loss-contingent sizing disabled.
- Reprices only an already-selected frozen ATR geometry at broker preflight; it does not re-select strategy logic.
- Verifies actual filled side, lot, SL, TP and actual stop risk before ACK.
- Never ACKs `PLACED` or `DONE_PARTIAL` market-send outcomes.
- Contains unsafe/ambiguous R7-owned exposure and enters persistent manual review instead of resubmitting.
- Gives raw/manual intents diagnostic preflight only; diagnostics cannot receive order-send authority.
- Uses one operator launcher: `START_XAU.bat`.
- Prohibits real/live-account execution.

## Current causal-producer authority chain

The producer phase uses an explicit fail-closed chain. Old V3 certification artifacts are not current authority.

1. **Source Bundle V4** — `r6_source_bundle.py` requires the exact canonical R6 ZIP and extracts only frozen Python entry source plus recursively resolved archive-local Python dependencies. It rejects duplicate/unsafe ZIP members, path escapes, symlinks, non-UTF-8 protected source, unresolved required local imports, direct/aliased/reflective dynamic imports, and prohibited validation/Holdout/research-result dependency paths. Existing output is replaceable only when the exact extractor ownership marker proves that directory belongs to this tool; an unowned directory is never recursively deleted.
2. **Source Probe V2** — AST-maps frozen entry engines without importing or executing strategy logic, recording normalized function source, AST hashes, spans, calls, names, literals and top-level assignments.
3. **Trusted Producer Replay V4 / Source Policy V4** — replays the candidate deterministically in a separate hash-covered worker process with a hard wall timeout, execution-event budget and bounded source/fixture/input/range/output resources. Unsafe imports/builtins, filesystem/network access, classes, global/nonlocal state, dunder access, `while`, exception handling, decorators/annotations, mutable module state/defaults, future/outcome-labelled inputs, nondeterminism and input mutation fail closed.
4. **Parity evidence** — binds the candidate stream to exact producer/source/fixture/isolation evidence and requires zero selection, priority, geometry, lot, timestamp and lookahead mismatches and zero retired-source emissions.
5. **Canonical-reference replay authority** — the reference stream must be regenerated from exact canonical frozen source. A supplied or self-authored reference stream is never authority by itself.
6. **Producer Admission Authority V5** — independently binds Source Bundle V4/Probe V2 provenance, canonical-reference replay, trusted Replay V4/Source Policy V4, process isolation, worker hash/resource contract, parity and clean Holdout/retuning boundaries.
7. **Candidate Seal V4** — re-runs V5 admission in an isolated baseline copy and hash-binds the complete candidate and replay-security contract. It cannot mutate the baseline, change readiness or unlock execution.
8. **Fused-release Precheck V4** — rejects old V3 seals, freshly reseals under current authority and requires the supplied/fresh V4 evidence and security contract to match exactly. PASS means only eligibility for a separately audited successor fused build.

## Exact candidate evidence layout

Candidate Seal V4 accepts only the defined candidate evidence set (plus a previously generated seal file, which is ignored and never treated as evidence):

- `r7_runtime/r6_causal_producer.py`
- `R7_R1_R6_SOURCE_PROBE.json`
- `R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json`
- `R7_R1_R6_PARITY_FIXTURES.jsonl`
- `R7_R1_R6_PRODUCER_REPLAY.json`
- `R7_R1_R6_REFERENCE_STREAM.jsonl`
- `R7_R1_R6_REFERENCE_REPLAY.json`
- `R7_R1_R6_PRODUCER_STREAM.jsonl`
- `R7_R1_R6_PARITY_ISOLATION.json`
- `R7_R1_R6_PRODUCER_PARITY.json`

Unexpected candidate files are rejected.

## Build Source Preflight V2

`BUILD_R7_R1.ps1` does not accept a generic source-preflight PASS. It pins all three authorities exactly:

- `R7_R1_CANONICAL_SOURCE_BUILD_PREFLIGHT_V2`
- `R7_R1_R6_SOURCE_BUNDLE_V4`
- `R7_R1_R6_SOURCE_PROBE_V2`

Before packaging it requires exact parent identity, source-only dependency closure, frozen-engine contract proof, prohibited validation/Holdout paths blocked, owned-output-only replacement proof, a valid ownership-marker SHA-256, strategy execution false, strategy retuning false, Final Holdout access false and producer admission false.

Those version/safety fields are written into `R7_R1_BUILD_VERIFICATION.json` and are checked again after clean ZIP extraction. Runtime package integrity separately validates operator-tool semantics as well as hashes, preventing a stale wrapper plus a recomputed stale manifest hash from passing.

## Execution lock

`CAUSAL_R6_PRODUCER_READY = False` is hard-coded and required by package integrity. Therefore automatic admitted-R6 execution is disabled even on demo.

A future successor would still require all of the following; changing the Boolean alone is insufficient:

- Producer Admission Authority V5 with `ready == true`
- trusted replay security-contract PASS
- canonical-reference replay PASS
- Final Holdout access false
- strategy retuning false
- `R7_R1_RUNTIME_CONFIG.json` with `"request_demo_execution": true`
- environment `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

Raw/manual intents never receive send authority.

## Decision inbox

The runtime may create `r7_r6_bridge/inbox` for staging only. Its strict parser can validate an already-admitted decision's schema/policy/parent/source/geometry/lot/timestamps/freshness/idempotency, but R7-R1 refuses automatic inbox execution while the causal-producer readiness lock is false.

This prevents a hand-written JSON file from masquerading as genuine frozen-R6 output.

## Important remaining boundary

The remaining autonomous-system gap is the exact causal R6 producer/reference implementation from canonical frozen source.

R7-R1 deliberately does not manufacture that logic from validation rows, outcome columns, an approximate selector or Final Holdout data. The exact source-derived implementation must pass the V4/V2/V4/V5/V4 authority chain above.

The canonical archive is available to the project, but the current ChatGPT process/Python backend has not been able to open ZIP members in this environment. That tooling limitation does not weaken the admission rules and is not permission to approximate the frozen strategy.

## Build/release boundary

The current builder is designed to create and clean-extraction-certify a producer-locked R7-R1 baseline against the exact canonical R6 ZIP. Candidate sealing/precheck evidence is preparation for a later explicitly audited fused successor; it is not a post-build patch and cannot change `causal_r6_producer_ready = false`.

Do not call the autonomous trading system production-ready, live-ready, `SEALED` or `FINAL` until the exact source-derived producer/reference executor is implemented, admitted and incorporated through a separately audited fused build. Live accounts remain prohibited.

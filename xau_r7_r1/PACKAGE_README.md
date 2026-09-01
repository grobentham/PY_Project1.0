# XAU V16 R7-R1 — Full Runtime Repair

## Status

R7-R1 is a hardened operational runtime around the frozen V16 R6 strategy package.

The **broker/risk/state/containment runtime repair scope is closed**: the adversarial repair audit has no known open Critical/High/Medium runtime defect. The runtime/test tree is exercised on Linux Python 3.9/3.11/3.13 and Windows Python 3.11, including Windows PowerShell parser checks and the Windows single-instance-lock path.

The **causal-producer verification infrastructure now uses V5 admission authority**. It includes exact-source extraction, local Python dependency closure, deep AST source mapping, resource-bounded deterministic candidate replay, parity evidence, canonical-reference replay authority, isolated candidate sealing and a non-promoting fused-release eligibility precheck.

The actual exact causal `r6_causal_producer.py` and exact canonical R6 reference executor have **not** been implemented/admitted from the frozen source yet. Therefore packaged R7-R1 order sending remains hard-locked even on demo. Real/live-account execution is prohibited.

R7-R1 does **not** retune R6 and does **not** access Final Holdout outcomes.

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

The launcher exposes the operational status/recovery functions plus a **non-trading producer-certification submenu**. There is no raw-order send option and no executable legacy R6 launcher option.

Producer certification actions are integrity-checked and cannot change the readiness constitution or send orders.

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

## Persistent-state and broker safety

SQLite uses WAL + `synchronous=FULL`. Runtime and intent state are replayed against the append-only hash-chained audit ledger before MT5 is touched.

Raw diagnostic preflight uses an ephemeral SQLite database and cannot contaminate the operational idempotency ledger. Connected account/server identity is pinned and rechecked on sensitive broker calls. Emergency containment only touches R7-R1-owned exposure.

## Frozen-R6 decision boundary

The runtime validates frozen schema/policy/parent/source/priority/family/geometry/lot/timestamps/freshness, permanent `AUX_RF_LTM` retirement and decision idempotency.

This validates an admitted decision's frozen contract. It does **not** prove that an upstream signal was genuinely calculated by frozen R6. Hand-written JSON therefore never receives autonomous execution authority.

## Exact-source producer workflow — V5 authority

The producer chain is deliberately fail-closed:

1. **Canonical source bundle V3** — requires the exact canonical R6 ZIP SHA-256, extracts only frozen Python source and its archive-local dependency closure, and rejects unsafe/dynamic/ambiguous source loading.
2. **Source probe V2** — records normalized AST source, function hashes, calls, assignments and literals without executing the strategy.
3. **Trusted producer replay V3 / source policy V3** — independently executes a candidate producer against causal fixtures twice and regenerates the producer stream. Candidate imports, filesystem/network APIs, unsafe builtins, classes, global/nonlocal state, dunder access, `while` loops, future/outcome-labelled inputs, nondeterminism and input mutation fail closed. Replay also enforces a 1 MiB producer-source cap, at most 4,096 fixtures, maximum input depth 64, at most 100,000 input nodes per fixture, bounded `range()` of at most 1,000,000 items, and a 1,000,000 Python call/line-event execution budget per candidate invocation.
4. **Parity evidence** — requires zero selection/priority/geometry/lot/timestamp mismatches, zero lookahead violations and zero retired-source emissions.
5. **Canonical reference replay authority** — independently regenerates the reference stream from the exact canonical R6 source. A supplied/self-authored reference stream is not authority.
6. **Producer Admission Authority V5** — requires both canonical-reference replay and the trusted candidate replay/parity chain.
7. **Candidate Seal V3** — re-runs V5 admission in an isolated baseline copy and records hashes for the producer, fixtures, producer replay, canonical reference stream, canonical reference replay attestation and producer stream.
8. **Fused-release Precheck V3** — verifies the locked baseline, freshly reseals the candidate and requires the supplied V3 seal to match. PASS only means eligibility for a separate successor fused-build step.

The replay limits are a fail-closed certification guard against obvious runaway Python candidates; they are not presented as a perfect operating-system sandbox or a complete defense against every possible expensive C-level Python operation.

The production canonical-reference executor is intentionally fail-closed today with:

`CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED_FROM_EXACT_R6_SOURCE`

This is the current hard boundary. It prevents synthetic or validation-derived logic from being presented as canonical R6 provenance.

## Causal-producer readiness lock

`CAUSAL_R6_PRODUCER_READY` remains hard-coded `False` in R7-R1 and the package manifest must attest the same value.

Even a future change of that Boolean is **not sufficient**. Runtime execution admission now also requires:

- `R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5`
- `ready == true`
- canonical-reference replay PASS
- Final Holdout access == false
- strategy retuned == false
- `R7_R1_RUNTIME_CONFIG.json` -> `"request_demo_execution": true`
- `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

A legacy V4 `ready=true` result cannot unlock execution.

## Crash and duplicate behavior

- Intent payloads are transactional and idempotent.
- Changed payload under the same intent ID fails closed.
- Broker magic/comment is checked for duplicates.
- `SUBMITTING` is persisted before `order_send()`.
- Restart recovery never automatically resubmits an ambiguous order.
- Reconciliation failures after a possible send attempt invoke scoped containment before terminal manual review.

## Integrity and build behavior

Every packaged invocation verifies inherited R6 files, protected R6 files, the exact R7 runtime Python set, launcher and producer operator toolkit hashes before mutable state is used.

`BUILD_R7_R1.ps1` now performs a mandatory **canonical frozen-source build preflight** against the exact R6 ZIP before it can report PASS. The preflight extracts only the Python dependency closure into the temporary build workspace, verifies the source-bundle/probe engine contract, records a non-sensitive summary in `R7_R1_BUILD_VERIFICATION.json`, and requires `strategy_executed=false`, `strategy_retuned=false`, `final_holdout_accessed=false`, and `producer_admitted=false`. The temporary extracted source is removed with the build workspace and is not packaged as a new source copy.

The builder then compiles, unit-tests and integrity-checks before ZIP creation and repeats verification after clean extraction. Clean extraction also requires the packaged build-verification record to contain canonical-source preflight PASS evidence bound to the canonical R6 SHA-256. The builder intentionally emits a **producer-locked baseline**.

Producer sealing/precheck evidence is preparation for a separately audited successor release. It is never a post-build patch or trading unlock mechanism.

R7-R1 should be described as a **repaired hardened fail-closed runtime with V5 producer-verification authority**. It is not yet an autonomous R6 trading system because the exact causal producer/reference executor remain unimplemented from canonical source.
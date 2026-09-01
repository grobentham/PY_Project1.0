# V16 R7-R1 Full Runtime Repair Audit

## Repair-closure status

**R7-R1 hardened runtime repair: COMPLETE for the implemented broker/risk/state/containment scope.**

The repaired runtime has no known open Critical/High/Medium defect from the adversarial runtime audit. The verified CI matrix covers Linux/Python 3.9, 3.11 and 3.13 plus Windows/Python 3.11. Windows also parses the release/source/producer PowerShell tools and exercises the `msvcrt` single-instance-lock path.

The producer-verification authority is now **V5**. It combines canonical source-bundle/probe provenance, trusted candidate replay, parity evidence and independent canonical-reference replay. Candidate Seal V3 and Fused-release Precheck V3 both require that V5 authority.

This closure does **not** claim autonomous R6 trading is implemented. `CAUSAL_R6_PRODUCER_READY` remains hard-frozen to `False`. The actual source-derived causal producer and canonical reference executor are not implemented/admitted, R6 is not retuned, and Final Holdout remains untouched.

## Canonical parent

- `XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`
- SHA-256 `8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

## Frozen policy retained

- R6 strategy logic unchanged.
- `AUX_RF_LTM` retired.
- Operating projected-stop risk cap 0.55%.
- Constitutional projected-stop risk ceiling 0.60%.
- Projected-equity floor S$850.
- Maximum canonical lot 0.02.
- One XAU exposure domain at a time.
- Martingale OFF.
- Recovery OFF.
- Averaging down OFF.
- Pyramiding OFF.
- Loss-contingent sizing OFF.
- Final Holdout access NO.
- Strategy retuning NONE.

## Closed runtime defects

| Area | Repair |
|---|---|
| Parent identity | Builder pins exact canonical R6 ZIP SHA and refuses mismatch. |
| Strategy preservation | Inherited parent tree and protected R6 strategy/policy files are hash verified. |
| Runtime integrity | Exact R7 Python path set, launcher and operator toolkit are hash covered; untracked runtime Python fails closed. |
| Protected path ambiguity | Verification uses exact manifest paths, so extracted source-workspace shadow copies cannot confuse protected-file resolution. |
| Canonical source build proof | Release builder now extracts the exact frozen Python dependency closure into a temporary workspace and AST-validates the required R5/R6 engine contract before PASS; source is not executed, retuned, or packaged as a new copy. |
| Persistent state | SQLite WAL + `synchronous=FULL`, transactional state/audit writes and semantic ledger replay. |
| State tampering | Deleted/injected intents/state/tickets, payload mutation and audit discontinuity fail closed. |
| Idempotency | Transactional local payload identity plus broker magic/comment duplicate reconciliation. |
| Single instance | Cross-platform process lock with Windows/Linux regression coverage. |
| Broker identity | Account/server pinning, Blueberry demo, SGD, symbol and trading-permission checks. |
| Exposure | All `XAUUSD.i` positions and pending orders count before new exposure is admitted. |
| Risk | MT5-derived stop loss + frozen commission + adverse deviation; 0.55%/0.60%/S$850/0.02-lot limits are wired into execution. |
| TOCTOU | Broker/risk preflight occurs again immediately before send. |
| Actual fill | ACK requires exact side/full volume/SL/TP and actual-fill stop-risk verification. |
| Partial/asynchronous fill | `PLACED`/`DONE_PARTIAL`, pending remainder or unstable DEAL-only state never ACK. |
| Containment | Unsafe/ambiguous R7-owned exposure is cancelled/flattened without touching unrelated XAU exposure. |
| Crash recovery | `SUBMITTING` persisted before send; restart reconciles and never auto-resubmits ambiguity. |
| Manual review | Persistent pause requires explicit acknowledgement, zero XAU exposure and zero in-flight intent to clear. |
| Raw intent bypass | Raw/manual intents are diagnostic-only and use an ephemeral audit store. |
| Launcher bypass | One launcher only; no raw-send or executable legacy-R6 path. |

## Producer provenance authority

### Source Bundle V3

The canonical-source extractor:

- requires the exact canonical R6 ZIP SHA;
- extracts the protected R5/R6 Python entry sources plus archive-local Python dependency closure;
- requires relative/local imports to resolve;
- rejects duplicate ZIP members, path traversal, symlinks, unsafe sizes and dynamic imports;
- records non-archive dependencies explicitly;
- excludes research/outcome/Holdout data.

### Build source preflight V1

`R7_R1_CANONICAL_SOURCE_BUILD_PREFLIGHT_V1` is now part of the release build gate. `BUILD_R7_R1.ps1` must successfully run the source-bundle extractor and source probe against the exact supplied canonical R6 ZIP before package creation.

The build preflight requires:

- canonical parent SHA match;
- source-only extraction;
- local Python dependency closure verified;
- required frozen engine contract present;
- strategy execution false;
- strategy retuning false;
- Final Holdout access false;
- producer admission false.

Only a non-sensitive summary and required-source hashes are written to `R7_R1_BUILD_VERIFICATION.json`. The normalized source/probe workspace stays under the GUID-named temporary build directory and is deleted by the builder cleanup. Clean extraction then requires the packaged build-verification record to carry source-preflight PASS evidence bound to the canonical R6 SHA.

### Source Probe V2

Without importing or executing frozen strategy code, the probe records normalized AST source, function AST hashes, source spans, call dependencies, referenced names, literals and top-level assignments.

### Trusted candidate replay

Candidate `r6_causal_producer.py` replay is deterministic and constrained:

- fixture corpus is causal-prefix only;
- future/outcome-labelled fixture inputs are rejected;
- producer executes twice per fixture;
- input mutation/nondeterminism fails;
- imports, classes, global/nonlocal state, dunder access, dynamic imports and unsafe builtins are prohibited;
- supplied producer stream must match independently regenerated bytes.

### Canonical-reference authority — V5

A supplied reference stream is **not** accepted as canonical provenance. `r6_reference_replay.py` must regenerate the reference stream from the exact canonical frozen R6 source bundle and causal fixtures and emit a hash-bound reference replay attestation.

`R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5` requires:

- exact source bundle/probe verification;
- canonical reference replay PASS;
- exact reference stream/fixture/source-bundle hashes tied to parity;
- trusted candidate replay/parity admission PASS;
- Final Holdout access false;
- strategy retuned false.

The production exact-source reference executor is intentionally not implemented yet and fails with:

`CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED_FROM_EXACT_R6_SOURCE`

That fail-closed error is the current honest architecture boundary.

## Runtime execution-authority bypass found and closed

During the V5 audit, `runtime.py` was found to still import the earlier V4 `producer_admission_status`. That created a future bypass: if the constitutional readiness Boolean were ever flipped, V4 `ready=true` evidence could potentially satisfy the runtime even though Seal/Precheck required V5.

This was repaired. The actual runtime unlock now uses V5 admission authority and additionally requires:

- `authority_version == R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5`;
- `ready == true`;
- `canonical_reference_replay_pass == true`;
- Final Holdout access false;
- strategy retuned false.

Regression tests explicitly prove that a legacy V4 `ready=true` result cannot unlock demo execution.

## Candidate Seal V3

`R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V3` is generated only after V5 admission passes in an isolated copy. Candidate evidence includes and hash-binds:

- producer module;
- source probe;
- source bundle manifest;
- causal fixtures;
- producer replay attestation;
- canonical reference stream;
- canonical reference replay attestation;
- producer stream;
- isolation manifest;
- parity report.

The seal cannot mutate the locked baseline or unlock execution.

## Fused-release Precheck V3

`R7_R1_R6_FUSED_RELEASE_PRECHECK_V3`:

- verifies locked baseline package integrity;
- validates supplied V3 seal;
- freshly reseals the candidate;
- requires all authority-bearing fields and hashes, including canonical-reference evidence, to match;
- reports future fused-build eligibility only.

It does not integrate code, change `CAUSAL_R6_PRODUCER_READY`, create an execution-enabled package or authorize trading.

## Cross-platform provenance repair

V5 testing exposed an OS-specific JSONL hash issue: Windows `write_text()` newline translation produced CRLF bytes while canonical replay produced LF bytes. Hash-bound canonical reference fixtures now use explicit UTF-8 `write_bytes()` with canonical compact JSONL, making provenance bytes identical across Windows/Linux.

The corrected V5 checkpoint passed:

- Linux Python 3.9 — PASS
- Linux Python 3.11 — PASS
- Linux Python 3.13 — PASS
- Windows Python 3.11 — PASS

including the real runtime V5 gate, canonical-reference authority, V3 seal/precheck and OS-independent reference hashing.

## Execution lock

`CAUSAL_R6_PRODUCER_READY = False` remains part of the R7-R1 constitution and package manifest.

Even in a future successor where that Boolean is deliberately changed, it is not sufficient by itself. Demo execution also requires current V5 authority plus the explicit config and environment unlocks.

Raw/manual intents can never receive send authority.

## Remaining implementation boundary

The remaining autonomous-system work is **not another broker-runtime repair**. It is the exact source-derived producer/reference implementation:

1. access the canonical R6 source/dependency bytes;
2. implement the exact canonical reference executor without reconstructing behavior from validation/outcome rows;
3. implement the causal `r6_causal_producer.py` from that same frozen source;
4. generate causal fixtures/reference/producer streams;
5. require zero parity mismatch and V5 admission;
6. produce V3 seal + V3 precheck;
7. only then create a separately audited fused successor release.

The canonical R6 ZIP is available in the project Library, but the current ChatGPT local command/Python backend fails before process start and the file service does not expose ZIP member source. This tooling limitation is not permission to approximate the strategy.

The new build-source preflight reduces the next release-build uncertainty: once `BUILD_R7_R1.ps1` is run in an environment that can open the canonical ZIP, source-closure readability and frozen-engine structure are mandatory build evidence rather than an unchecked assumption. It does not, by itself, authorize or synthesize the missing causal executor.

## Build/release status

`BUILD_R7_R1.ps1` is designed to create and clean-extraction-certify a **producer-locked R7-R1 baseline** while preserving canonical R6 bytes. It packages/hash-covers the producer operator toolkit and now requires canonical source-bundle/probe preflight against the exact R6 archive before PASS.

No legitimate producer-enabled fused ZIP has been created yet.

## Closure rule

The R7-R1 broker/risk/state/containment repair and V5 producer-verification authority are implemented and fail closed.

Do not call the autonomous trading system `SEALED`, `FINAL`, production-ready or live-ready. Do not enable automatic execution until the exact canonical source executor and causal producer are implemented, V5-admitted, V3-sealed, V3-prechecked and incorporated through a separately audited successor build. Real/live-account execution remains prohibited.
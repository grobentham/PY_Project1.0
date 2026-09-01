# V16 R7-R1 Full Runtime Repair Audit

## Repair-closure status

**R7-R1 hardened runtime repair: COMPLETE for the implemented broker/risk/state/containment scope.**

The repaired runtime has no known open Critical/High/Medium broker/risk/state/containment defect from the current adversarial repair program. The verified CI matrix covers Linux/Python 3.9, 3.11 and 3.13 plus Windows/Python 3.11. Windows parses the release/source/producer PowerShell tools, semantically checks their authority contracts, and exercises the `msvcrt` single-instance-lock path.

The producer-verification authority is **V5**. It combines Source Bundle V4 / Source Probe V2 provenance, isolated/resource-bounded trusted candidate replay V4, parity evidence and independent canonical-reference replay. Candidate Seal V4 and Fused-release Precheck V4 both require that V5 authority.

This closure does **not** claim autonomous R6 trading is implemented. `CAUSAL_R6_PRODUCER_READY` remains hard-frozen to `False`. The actual exact source-derived causal producer and canonical-reference executor are not implemented/admitted, R6 is not retuned, and Final Holdout remains untouched.

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

## Closed runtime/software defects

| Area | Repair |
|---|---|
| Parent identity | Builder pins the exact canonical R6 ZIP SHA and refuses mismatch. |
| Strategy preservation | Inherited parent tree and protected R6 strategy/policy files are hash verified. |
| Runtime integrity | Exact R7 Python path set, launcher and operator toolkit are hash covered; untracked runtime Python fails closed. |
| Operator semantic integrity | Operator wrappers are checked for current authority semantics in addition to hashes; a stale wrapper with a recomputed stale manifest hash cannot pass. |
| Protected path ambiguity | Verification uses exact manifest paths, so source-workspace shadow copies cannot confuse protected-file resolution. |
| Canonical source build proof | Build Source Preflight V2 requires Source Bundle V4 + Source Probe V2, exact parent identity, source-only dependency closure, engine-contract proof, prohibited-path blocking and owned-output-only replacement before PASS. |
| Source-path leakage | Source Bundle V4 rejects validation/Holdout/research-result dependency paths instead of extracting them into producer evidence. |
| Dynamic-import ambiguity | Direct, aliased and reflective dynamic-import constructions fail closed. |
| Unsafe output replacement | Source extraction never recursively deletes an arbitrary existing output folder; replacement requires its exact valid extractor ownership marker. Symlink/unowned/corrupt-marker outputs are rejected. |
| Producer certification runaway | Trusted Replay V4 executes the candidate in a separate hash-covered worker process with a 60-second wall timeout, 1,000,000 Python call/line-event budget, bounded source/fixture/input/range/output sizes, and rejects `while` loops. |
| Replay budget interception | Candidate `try/except`/`try*`, executable decorators/annotations, mutable top-level state and mutable/executable defaults are rejected. |
| Replay downgrade | V5 authority and runtime require current Replay V4/Source Policy V4, process isolation, worker hash and exact resource limits. |
| Seal/precheck downgrade | Seal V4 carries the replay-security contract; Precheck V4 rejects V3 seals and requires supplied/fresh worker-security contracts to match. |
| Builder downgrade | `BUILD_R7_R1.ps1` pins Build Preflight V2 / Source Bundle V4 / Source Probe V2 before packaging and after clean extraction; CI statically rejects V1/V3 regression. |
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
| Crash recovery | `SUBMITTING` is persisted before send; restart reconciles and never auto-resubmits ambiguity. |
| Manual review | Persistent pause requires explicit acknowledgement, zero XAU exposure and zero in-flight intent to clear. |
| Raw intent bypass | Raw/manual intents are diagnostic-only and use an ephemeral audit store. |
| Launcher bypass | One launcher only; no raw-send or executable legacy-R6 path. |

## Producer provenance authority

### Source Bundle V4

`R7_R1_R6_SOURCE_BUNDLE_V4` is the current canonical-source extractor contract. It:

- requires the exact canonical R6 ZIP SHA;
- extracts protected R5/R6 Python entry sources plus archive-local Python dependency closure;
- requires relative/local imports to resolve;
- rejects duplicate ZIP members, traversal/unsafe paths, symlinks, unsafe sizes and non-UTF-8 protected source;
- rejects direct, aliased and reflective dynamic imports;
- rejects prohibited validation/Holdout/research-result source dependencies before output is admitted;
- records true non-archive dependencies instead of falsely extracting them;
- writes an ownership marker for its output workspace;
- allows replacement only when the existing directory carries the exact valid ownership marker;
- refuses to delete unowned, symlinked or corrupt-marker output locations;
- reports strategy execution false, strategy retuning false, Final Holdout access false and producer admission false.

Regression coverage includes prohibited local dependencies, aliased/reflective dynamic imports, unsafe archive members, unresolved local helpers, output symlinks, unowned directories, corrupt ownership markers and safe replacement of genuinely owned output.

### Build Source Preflight V2

`R7_R1_CANONICAL_SOURCE_BUILD_PREFLIGHT_V2` is the release-build source authority. It requires:

- exact canonical-parent SHA;
- `R7_R1_R6_SOURCE_BUNDLE_V4`;
- `R7_R1_R6_SOURCE_PROBE_V2`;
- source-only extraction;
- archive-local Python dependency closure verified;
- required local imports resolved;
- dynamic imports disabled;
- required frozen engine contract present;
- prohibited source paths blocked;
- owned-output-only replacement proven;
- a valid extractor ownership-marker SHA-256;
- strategy execution false;
- strategy retuning false;
- Final Holdout access false;
- producer admission false.

The builder now pins these exact V2/V4/V2 versions and safety fields. `R7_R1_BUILD_VERIFICATION.json` records top-level source-preflight/bundle/probe versions, prohibited-path proof, owned-output proof and the nested preflight evidence. Clean extraction rechecks those same fields plus canonical-parent identity before the package can report PASS.

### Source Probe V2

Without importing or executing frozen strategy code, the probe records normalized AST source, function AST hashes, source spans, call dependencies, referenced names, literals and top-level assignments.

### Trusted candidate Replay V4 / Source Policy V4

Candidate `r6_causal_producer.py` replay is deterministic, causal-input constrained, process isolated and resource bounded:

- fixture corpus is causal-prefix only;
- future/outcome-labelled fixture inputs are rejected;
- producer executes twice per fixture;
- input mutation/nondeterminism fails;
- imports, classes, global/nonlocal state, dunder access, dynamic imports and unsafe builtins are prohibited;
- `while` loops and all `try/except`/`try*` constructs are rejected before execution;
- decorators and annotations are rejected to prevent executable definition-time behavior;
- top-level constants and function defaults must be immutable literals;
- producer source is capped at 1 MiB;
- fixture corpus is capped at 4,096 records;
- input depth is capped at 64 and input nodes at 100,000 per fixture;
- sandbox `range()` is capped at 1,000,000 items;
- each producer invocation has a 1,000,000 Python call/line trace-event budget;
- replay runs in a separate Python worker with a hard 60-second wall timeout;
- worker stream/report outputs are size bounded;
- fixture, producer and worker hashes are rechecked after replay;
- supplied producer stream must match independently regenerated bytes.

The isolated worker is part of the package's exact `r7_runtime/**/*.py` hash set. Replacing it invalidates package integrity.

These controls isolate the verifier from candidate operations that can evade Python line tracing. They are not claimed as a complete hostile-host/OS sandbox.

### Canonical-reference authority — V5

A supplied reference stream is not accepted as canonical provenance. `r6_reference_replay.py` must regenerate the reference stream from exact canonical frozen source plus causal fixtures and emit a hash-bound reference-replay attestation.

`R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5` requires:

- Source Bundle V4 / Source Probe V2 verification;
- prohibited-path, dependency-closure and source-integrity evidence;
- canonical-reference replay PASS;
- exact reference stream/fixture/source-bundle hashes tied to parity;
- trusted candidate replay/parity admission PASS;
- replay version `R7_R1_R6_PRODUCER_REPLAY_V4`;
- source policy `R7_R1_R6_PRODUCER_SOURCE_POLICY_V4`;
- process isolation PASS and a valid worker-module SHA-256;
- exact wall-time/resource-limit contract;
- all no-import/no-state/no-exception/no-lookahead/no-outcome guards intact;
- Final Holdout access false;
- strategy retuned false.

Runtime execution independently requires the V5 authority and replay-security-contract PASS in addition to canonical-reference replay.

The production exact-source reference executor is intentionally not implemented yet and fails with:

`CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED_FROM_EXACT_R6_SOURCE`

That is the current honest architecture boundary.

## Runtime execution-authority bypass closed

The runtime does not accept older candidate-admission readiness as execution authority. A future readiness switch change would still require:

- `authority_version == R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5`;
- `ready == true`;
- `trusted_replay_security_contract_pass == true`;
- `canonical_reference_replay_pass == true`;
- Final Holdout access false;
- strategy retuned false.

Regression tests prove that legacy readiness, downgraded replay versions and disabled process isolation cannot unlock demo execution.

## Candidate Seal V4

`R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V4` is generated only after V5 admission passes in an isolated copy. It hash-binds:

- producer module;
- source probe;
- Source Bundle V4 manifest;
- causal fixtures;
- producer replay attestation;
- canonical reference stream;
- canonical reference replay attestation;
- producer stream;
- isolation manifest;
- parity report;
- `trusted_replay_security_contract_pass=true`;
- exact replay/source-policy versions, process-isolation claim, worker SHA-256, wall timeout and replay resource limits.

It cannot mutate the locked baseline or unlock execution.

## Fused-release Precheck V4

`R7_R1_R6_FUSED_RELEASE_PRECHECK_V4`:

- verifies locked baseline package integrity;
- rejects legacy V3 seals;
- validates the supplied V4 replay-security contract;
- freshly reseals under current V5 authority;
- requires all authority-bearing hashes and the full replay worker/security contract to match;
- reports future fused-build eligibility only.

It does not integrate code, change `CAUSAL_R6_PRODUCER_READY`, create an execution-enabled package or authorize trading.

## Cross-platform provenance / CI

The supported regression matrix is Linux Python 3.9/3.11/3.13 and Windows Python 3.11. Windows additionally:

- parses all release/source/certification PowerShell tools;
- checks builder source-authority tokens for Preflight V2 / Bundle V4 / Probe V2;
- checks extraction wrapper Source Bundle V4 safety tokens;
- checks Seal/Precheck V4 replay-security authority tokens;
- rejects legacy V1/V3 authority references.

Runtime unit coverage also proves that a stale extraction/seal/precheck wrapper cannot become valid merely by recomputing its manifest hash.

## Execution lock

`CAUSAL_R6_PRODUCER_READY = False` remains part of the R7-R1 constitution and package manifest.

Even in a future successor where that Boolean is deliberately changed, it is not sufficient by itself. Demo execution also requires current V5 authority, trusted replay security-contract PASS, canonical-reference replay PASS, and explicit config/environment unlocks.

Raw/manual intents can never receive send authority. Real/live-account execution remains prohibited.

## Remaining implementation boundary

The remaining autonomous-system work is the exact source-derived producer/reference implementation:

1. access exact canonical R6 source/dependency bytes;
2. implement the exact canonical reference executor without reconstructing behavior from validation/outcome rows;
3. implement causal `r6_causal_producer.py` from the same frozen source;
4. generate causal fixtures/reference/producer streams;
5. require zero parity mismatch and V5 admission;
6. produce V4 seal + V4 precheck;
7. create a separately audited fused successor release.

The canonical R6 ZIP is available in the project Library, but the current ChatGPT process/Python backend has failed before ZIP-member inspection. This tooling limitation is not permission to approximate the strategy or publish canonical strategy IP.

## Build/release status

`BUILD_R7_R1.ps1` is designed to create and clean-extraction-certify a **producer-locked R7-R1 baseline** while preserving canonical R6 bytes. It hash-covers the producer operator toolkit and requires exact Build Preflight V2 / Source Bundle V4 / Source Probe V2 evidence before PASS.

No legitimate producer-enabled fused ZIP has been created yet.

## Closure rule

The implemented R7-R1 broker/risk/state/containment repair and producer-verification authority are fail-closed.

Do not call the autonomous trading system `SEALED`, `FINAL`, production-ready or live-ready. Do not enable automatic execution until the exact canonical source executor and causal producer are implemented, V5-admitted, V4-sealed, V4-prechecked and incorporated through a separately audited successor build. Real/live-account execution remains prohibited.

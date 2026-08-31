# V16 R7-R1 Full Runtime Repair Audit

## Repair-closure status

**R7-R1 hardened runtime repair: COMPLETE for the implemented broker/risk/state/containment scope.**

The repaired runtime has no known open Critical/High/Medium defect from the adversarial runtime audit. The CI matrix covers Linux/Python 3.9, 3.11 and 3.13 plus Windows/Python 3.11. The Windows lane parses all release/source/producer PowerShell operator scripts and exercises the Windows `msvcrt` single-instance-lock path.

The producer-verification infrastructure is also implemented through source-bundle V3, source-probe V2, parity V2, admission V3, isolated candidate sealing and non-promoting fused-release precheck.

This closure does **not** claim autonomous R6 trading is implemented. `CAUSAL_R6_PRODUCER_READY` remains hard-frozen to `False`. The actual exact causal producer is not admitted/fused, the canonical R6 strategy is not retuned, and Final Holdout remains untouched.

## Purpose

R7-R1 is a replacement operational-runtime repair built around the exact canonical frozen R6 package. It is not a strategy promotion and does not read Final Holdout outcomes.

Canonical parent:

- `XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`
- SHA-256 `8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

## Closed software defects and hardened boundaries

| Area | R7-R1 repair |
|---|---|
| Parent identity | Builder pins the exact canonical R6 ZIP SHA-256 and refuses any mismatch. |
| Strategy preservation | Builder hashes the inherited parent tree and protected R6 strategy/policy files; inherited files remain byte-identical except the intentional root launcher replacement. |
| Runtime integrity | Runtime Python files and replacement launcher are hashed in the package manifest and checked before mutable runtime state is opened. |
| Producer overclaim/bypass | Current package manifest/runtime require `causal_r6_producer_ready == false`; automatic decision execution cannot unlock while the exact producer is absent. |
| Source extraction | Source-bundle V3 extracts only frozen Python entry source plus recursively resolved archive-local Python dependency closure from the canonical archive. Required local imports must resolve; unsafe paths, duplicates, symlinks, size violations and dynamic imports fail closed. |
| External dependencies | Imports not present in the canonical archive are recorded as unresolved non-archive imports rather than silently treated as local source. |
| Source implementation map | Source-probe V2 AST-maps frozen entry engines without importing/executing strategy code and records normalized source, AST hashes, spans, calls, referenced names, literals and assignments. |
| Source provenance | Producer admission verifies every source-closure file against both its bundle hash and the canonical parent-tree hash. Research/Final-Holdout source paths are prohibited. |
| Parity provenance | Parity V2 is machine-derived from reference/producer streams and is hash-bound to the source bundle, source probe, producer module, causal isolation manifest and both streams. |
| Causal parity | Admission requires zero mismatch, zero lookahead violation, full frozen-source coverage and zero retired `AUX_RF_LTM` emission. |
| Candidate sealing | Candidate is verified only in a temporary copy of the locked baseline; sealing cannot mutate protected R6 bytes, flip readiness or unlock execution. Seal is repeatable without treating its own prior generated seal as candidate evidence. |
| Fused-release eligibility | Non-promoting precheck verifies baseline package integrity, freshly reseals the candidate and requires the supplied seal to match authority-bearing fields. PASS grants eligibility for a later fused-build step only; it creates no package and changes no readiness state. |
| Persistent state | SQLite WAL + `synchronous=FULL`, transactional writes, append-only hash-chained audit ledger, semantic state replay, exact intent-table reconciliation, broker-ticket replay and audited runtime-state reconciliation. |
| Deleted/injected state | Deleting audited state, injecting unaudited state/intents, changing payload/state/tickets, or breaking the audit chain fails closed. |
| Risk governor wiring | Every executable decision passes broker-derived preflight risk before `order_check` and again immediately before `order_send`. |
| Projected risk source | Caller cannot provide projected loss. MT5 `order_calc_profit()` plus frozen commission assumptions are used; pre-send risk budgets configured adverse deviation. |
| Actual-fill risk | ACK requires actual broker fill side, volume, SL, TP, submitted protection and stop-risk verification. Unsafe actual fills trigger scoped containment. |
| Partial/asynchronous fills | `PLACED` and `DONE_PARTIAL` are never ACKed. They enter containment + `MANUAL_REVIEW_NO_RESUBMIT`. |
| Broker protection mutation | Immediate fills must preserve submitted rounded SL/TP; altered/missing protection is contained. |
| Duplicate orders | Local payload-hash idempotency plus broker magic/comment reconciliation. |
| Crash recovery | `RESERVED`/`PREFLIGHT_OK` are abandoned before send; `SUBMITTING`/`SUBMITTED` reconcile against broker state and never auto-resubmit. |
| Post-send ambiguity | Missing ACK, unstable DEAL-only state, pending remainder, exposure mismatch, risk breach, query failure or containment failure force `MANUAL_REVIEW_NO_RESUBMIT`. |
| Emergency containment | Cancels/closes only R7-R1-owned intent exposure. It does not touch unrelated XAU positions; entry spread limits cannot block an emergency exit. |
| Manual-review pause | Pause is persisted in SQLite before evidence archival and mirrored to filesystem. Resume requires exact acknowledgement, zero XAU exposure and zero in-flight intents. |
| Account switching | Connected login/server are pinned and revalidated on sensitive broker reads. |
| Broker permissions | Demo trade mode, Blueberry server identity, SGD currency, terminal/API/Expert/symbol trading permissions and symbol availability are checked. |
| Exposure domain | Every current `XAUUSD.i` position and pending order is counted regardless of magic before new exposure may be admitted. |
| Raw-order bypass | Raw/manual JSON is diagnostic-only; actual send authority is reserved for the frozen-R6 producer/adapter chain. |
| Diagnostic-state pollution | Raw diagnostic preflight uses a temporary SQLite store and cannot mutate operational idempotency/audit state. |
| Operator bypass | Single launcher exposes status/recovery/no-send diagnostics/staging/manual-review operations. Executable legacy-launcher bypass is removed; original R6 launcher remains evidence only. |
| Decision replay | Decision emission time and underlying R6 signal timestamp have independent freshness limits. |
| Inbox safety | Direct-child-only JSON ingestion, no symlinks, size cap, stable-read check, SHA evidence, quarantine/archive buckets and duplicate suppression. |
| Single-instance enforcement | Cross-platform process lock is implemented and contention/release is regression-tested. |
| Build verification | Builder compiles/runs offline regression before packaging and after clean extraction, then verifies inherited/runtime hashes. |
| Windows release engineering | Windows CI parses builder, source extractor/probe, producer seal and fused-precheck scripts, compiles runtime/tests and runs offline regression. |
| Python compatibility | Linux CI executes full runtime/tests on Python 3.9, 3.11 and 3.13. |

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

`CAUSAL_R6_PRODUCER_READY = False` is part of the current runtime constitution and package-integrity manifest. Automatic R6 decision execution therefore remains hard-disabled regardless of operator configuration.

A producer-enabled successor would require, at minimum:

1. an exact source-derived causal R6 producer with complete source-bundle/probe/parity/admission evidence;
2. a matching isolated candidate seal;
3. a matching non-promoting fused-release precheck;
4. a separate successor fused build that intentionally changes the producer constitution and regenerates package-integrity hashes;
5. the existing demo-only operator gates.

Neither candidate seal nor fused-release precheck is authority to change item 4. Raw/manual intents can never receive order-send authority.

## Remaining architecture boundary — not an open runtime repair defect

The remaining autonomous-system gap is the **actual exact causal R6 decision producer and its later explicit fused successor build**.

R7-R1 deliberately does not reconstruct frozen strategy selection from validation/outcome rows. The producer must be derived from the canonical frozen R5/R6 source/dependency map, produce causal-prefix decisions and pass the complete zero-mismatch evidence chain.

The canonical R6 archive has been successfully recovered/materialized in the current project workflow. However, the current ChatGPT local command/Python execution backend has failed before process start, and the file service does not expose parsed member source from the ZIP. This tooling limitation is not treated as permission to synthesize strategy logic from outcomes.

## Verification status

The established CI matrix includes:

- Linux Python 3.9.
- Linux Python 3.11.
- Linux Python 3.13.
- Windows Python 3.11.
- Windows PowerShell parser validation for release/source/producer operator scripts.
- Windows single-instance-lock contention path.
- Diagnostic preflight isolation.
- Parent/strategy/producer-lock integrity.
- Source-bundle/probe/parity/admission regression coverage.
- Isolated candidate sealing and reseal behavior.
- Non-promoting fused-release precheck regression coverage.

Final Holdout accessed: **NO**. Strategy retuned: **NO**.

The release ZIP still must be produced by `BUILD_R7_R1.ps1` against the exact canonical R6 ZIP and pass its clean-extraction verification before a package can be called **release-built**. That R7-R1 ZIP remains a producer-locked baseline by design.

## Security/threat-model note

The package and SQLite hash chains provide fail-closed integrity checking against file/state corruption and ordinary tampering. They are not a cryptographic trust anchor against an attacker who controls the Windows host and can replace the launcher, Python interpreter and verifier together. Host security/code signing is a separate deployment concern.

## Closure rule

The **R7-R1 runtime repair phase is closed** at the verified hard-locked decision-consumer boundary, and the producer verification/release-preparation infrastructure is implemented without weakening that lock.

Do not call the package `SEALED`, `FINAL`, production-ready or live-ready. Do not enable autonomous execution until the exact causal R6 producer is implemented, admitted, sealed, prechecked and incorporated through a separate audited fused successor build. Real/live-account execution remains prohibited.

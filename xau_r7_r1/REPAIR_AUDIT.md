# V16 R7-R1 Full Runtime Repair Audit

## Repair-closure status

**R7-R1 hardened runtime repair: COMPLETE for the currently implementable runtime scope.**

The latest repaired runtime has no known open Critical/High/Medium defect from the adversarial repair audit. It passes the full offline regression on Linux/Python 3.9, 3.11 and 3.13 and on Windows/Python 3.11. The Windows lane also parses `BUILD_R7_R1.ps1` with the PowerShell parser and exercises the Windows `msvcrt` single-instance-lock path.

This closure does **not** claim autonomous R6 trading is implemented. `CAUSAL_R6_PRODUCER_READY` remains hard-frozen to `False`, so automatic decision execution cannot unlock until an exact causal producer is derived from the canonical frozen R6 source and separately audited. The canonical R6 source archive is not modified and Final Holdout remains untouched.

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
| Producer overclaim/bypass | Package manifest and runtime require `causal_r6_producer_ready == false`; the runtime cannot unlock automatic decision execution while the exact producer is absent. Missing/true producer-lock fields fail package integrity. |
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
| Raw-order bypass | Raw/manual JSON has diagnostic preflight capability only and no send authority. Actual send authority is reserved for the frozen-R6 producer/adapter chain. |
| Diagnostic-state pollution | Raw diagnostic preflight now uses a temporary ephemeral SQLite store. It cannot reserve IDs or mutate the operational idempotency/audit ledger. |
| Operator bypass | Single launcher exposes status, recovery, no-send diagnostic preflight, staging-only R6 inbox access and explicit pause resume. The executable legacy-launcher bypass was removed. Original R6 launcher bytes remain evidence only. |
| Decision replay | Both decision emission time and the underlying R6 signal timestamp have independent freshness limits; a stale signal cannot be revived with a fresh emission timestamp. |
| Inbox safety | Direct-child-only JSON ingestion, no symlinks, size cap, stable-read check, SHA-256 evidence, quarantine/archive buckets and duplicate suppression. |
| Single-instance enforcement | Cross-platform process lock is implemented and contention/release is regression-tested, including the Windows `msvcrt` implementation in CI. |
| Build verification | Builder compiles and runs the offline regression suite before packaging and again after clean ZIP extraction, then verifies inherited/runtime hashes. |
| Windows release engineering | Windows CI parses the PowerShell builder, validates the launcher template is present, compiles the runtime/tests and runs the full offline regression. |
| Python compatibility | Linux CI executes the full runtime/tests on Python 3.9, 3.11 and 3.13. |

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

`CAUSAL_R6_PRODUCER_READY = False` is part of the current runtime constitution and package-integrity manifest. Therefore automatic R6 decision execution remains hard-disabled regardless of operator configuration.

A future producer-enabled successor would require all three independent conditions:

1. an exact audited causal R6 producer admitted in code and package integrity;
2. `R7_R1_RUNTIME_CONFIG.json` -> `"request_demo_execution": true`;
3. `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`.

Raw/manual intents can never receive order-send authority. They are diagnostic-only and use ephemeral state.

## Remaining architecture boundary — not an open runtime repair defect

The broker/risk/state/containment runtime is repaired. The missing item is a **new exact implementation phase**: a causal frozen-R6 decision producer.

R7-R1 deliberately does not reconstruct frozen strategy selection from validation/outcome rows. The producer must be derived from the exact canonical R5/R6 feature/selector source so it can prove causal parity with the frozen research implementation. Until those exact archive sources are programmatically accessible and the producer is implemented/audited, the hard lock remains `False`.

This boundary is intentional fail-closed behavior, not permission to synthesize a replacement strategy.

## Verification status

Repair-closure verification includes:

- Linux Python 3.9: PASS.
- Linux Python 3.11: PASS.
- Linux Python 3.13: PASS.
- Windows Python 3.11: PASS.
- Windows PowerShell parser check for `BUILD_R7_R1.ps1`: PASS.
- Windows single-instance-lock contention path: covered by the offline regression.
- Diagnostic preflight isolation: covered by regression.
- Parent/strategy/producer-lock integrity: covered by regression.
- Final Holdout accessed: NO.
- Strategy retuned: NO.

The release ZIP still must be produced by `BUILD_R7_R1.ps1` against the exact canonical R6 ZIP and pass its built-in clean-extraction verification before a package can be called **release-built**.

## Security/threat-model note

The package and SQLite hash chains provide fail-closed integrity checking against file/state corruption and ordinary tampering. They are not a cryptographic trust anchor against an attacker who already controls the Windows host and can replace the launcher, Python interpreter and verification code together. Host security/code signing is a separate deployment concern and is not represented as a solved runtime property.

## Closure rule

The **R7-R1 runtime repair phase is closed** at the verified hard-locked decision-consumer boundary. Do not call the package `SEALED`, `FINAL`, production-ready or live-ready. Do not enable autonomous execution until the exact causal R6 producer is implemented and audited. Real/live-account execution remains prohibited.

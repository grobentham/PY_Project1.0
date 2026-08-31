# V16 R7-R1 Full Repair Audit

## Why R7-R1 exists

The prior R7 overlay was rejected. It created scaffolding but overstated its maturity. R7-R1 is a replacement repair line built from the canonical frozen R6 package, not a promotion of the failed overlay.

## Original audit findings and R7-R1 closure

| Original finding | R7-R1 repair |
|---|---|
| Canonical R6 not authenticated | Builder pins exact R6 SHA-256 `8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7` and refuses any mismatch. |
| Risk governor dead code | `ExecutionEngine._broker_preflight()` calls the wired `RiskGovernor` before `order_check` and again immediately before `order_send`. |
| No actual execution pipeline | Explicit intent -> local idempotency -> broker duplicate check -> account/quote/exposure snapshot -> broker-derived risk -> risk gate -> `order_check` -> second preflight -> durable `SUBMITTING` -> optional `order_send` -> broker reconciliation. |
| Duplicate protection not wired | SQLite payload-hash idempotency is in the submit path and a broker-side magic/comment duplicate check protects against local database loss. |
| No restart recovery | In-flight states are reconciled against broker positions/orders/deal history. Ambiguous send states never auto-resubmit. |
| No single-instance protection | Cross-platform OS file lock wraps each runtime command. |
| Audit chain not transactional | Audit and state-transition writes use `BEGIN IMMEDIATE`; idempotency-collision evidence is committed before the collision exception is raised. |
| Projected risk trusted caller input | Caller cannot supply projected loss. Runtime uses MT5 `order_calc_profit()` from current executable quote to stop plus the frozen validation round-turn commission burden. |
| Existing launcher blindly replaced | Original R6 `START_XAU.bat` bytes are hashed and preserved as non-executable evidence. The single R7-R1 launcher can invoke those exact preserved bytes temporarily from package root. |
| Self-test never run | Builder refuses release unless Python compile + offline unit suite + offline runtime integrity status pass before packaging and again after clean ZIP extraction. |
| No compile/import gate | Builder uses `compileall` before and after packaging. |
| Strategy-integrity claim was unproven | Builder hashes every inherited parent file and the protected R6 strategy/policy set. All inherited files except the deliberate root launcher replacement must remain byte-identical. |
| Runtime code was not protected | Builder records SHA-256 for R7-R1 runtime Python files and the replacement launcher; runtime verifies those hashes before creating mutable state. |
| Position count only used one magic | Risk exposure snapshot counts every current `XAUUSD.i` position and pending order, regardless of magic. |
| Demo protection was configurable | Demo-only and Blueberry server identity are hard-coded. Config cannot disable them. |
| Tick/spread guards could be weakened | Config may only make those limits stricter than the hard maximums. |
| Post-send broker state was insufficiently checked | ACK requires broker reconciliation plus post-send exposure proof. Count/lot anomalies go to `MANUAL_REVIEW_NO_RESUBMIT`. |
| MT5 query errors could look like empty state | Positions, orders and history `None` responses now fail closed. |

## Frozen policy retained

- R6 strategy logic remains inherited.
- `AUX_RF_LTM` remains retired.
- Operating projected-stop risk cap: 0.55%.
- Constitutional projected-stop risk ceiling: 0.60%.
- Projected-equity floor: S$850.
- Maximum canonical lot: 0.02.
- One XAU exposure domain at a time.
- Martingale OFF.
- Recovery OFF.
- Averaging down OFF.
- Pyramiding OFF.
- Loss-contingent sizing OFF.
- Final Holdout access: NO.
- Strategy retuning: NONE.

## Execution safety boundary

Order sending is disabled by default. Demo sending requires both:

1. `R7_R1_RUNTIME_CONFIG.json` -> `"request_demo_execution": true`
2. environment variable `XAU_R7_R1_ENABLE_DEMO_EXECUTION=YES_I_ACCEPT_DEMO_ONLY`

The broker gateway independently rejects non-Blueberry servers, non-demo servers, non-SGD accounts and symbols other than `XAUUSD.i`.

## Important remaining architecture boundary

R7-R1 does **not** pretend the frozen research/backtest engine is already a causal live-signal generator. The runtime accepts explicit R6-derived intent JSON at a narrow adapter boundary. A future automatic signal adapter must prove that its live feature construction and decision timing reproduce the frozen R6 policy before it is allowed to feed this execution engine automatically.

That boundary is intentional and must not be bypassed by copying backtest rows directly into live orders.

## Release rule

Do not call R7-R1 `SEALED`, `FINAL`, or production-ready until `BUILD_R7_R1.ps1` successfully builds against the exact canonical R6 ZIP and the generated ZIP passes its clean-extraction verification. Real/live account trading remains prohibited by R7-R1 regardless.

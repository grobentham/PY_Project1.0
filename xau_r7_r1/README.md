# XAU V16 R7-R1 — Full Runtime Repair

This branch repairs the failed R7 overlay. It is a software-engineering successor around the frozen canonical R6 package; it does not retune strategy logic and does not read Final Holdout outcomes.

## Canonical parent

`XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip`

Required SHA-256:

`8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7`

The builder refuses any parent with a different digest.

## Repair goals

- Verify the canonical parent ZIP before extraction.
- Hash every inherited parent file and verify all inherited files remain byte-identical except the intentionally replaced top-level launcher.
- Preserve the original launcher bytes as non-executable frozen evidence.
- Verify critical R6 strategy/policy files again at runtime.
- Add SQLite WAL + `synchronous=FULL` transactional state.
- Add a hash-chained audit ledger with `BEGIN IMMEDIATE` writes.
- Add idempotent intent reservation and a crash-safe order state machine.
- Add single-instance locking.
- Derive projected stop loss from MetaTrader 5 `order_calc_profit`; never trust a caller-supplied loss number.
- Enforce one XAUUSD.i exposure domain across positions and pending orders.
- Enforce the frozen 0.55% operating cap, 0.60% constitutional ceiling, S$850 projected-equity floor, 0.02 lot maximum, and permanent `AUX_RF_LTM` retirement.
- Keep martingale, recovery, averaging down, pyramiding and loss-contingent sizing disabled.
- Keep demo-only protection hard-coded in R7-R1.
- Use `order_check` before any `order_send`.
- Never automatically resubmit an ambiguous in-flight order after a crash.
- Keep order sending disabled by default and require an explicit demo-only environment unlock.
- Run compile, unit, integrity, package-extraction and offline-runtime verification before creating a release ZIP.

## Important boundary

R7-R1 repairs the operational broker/risk/state layer. The frozen R6 research engine is preserved. Automatic live signal generation from the research/backtest engine is not invented or silently approximated. Broker execution accepts explicit R6-derived `OrderIntent` JSON at the adapter boundary until a separately auditable causal live-signal adapter is implemented.

That limitation is deliberate: the repair must not turn a research backtest API into a fake live strategy implementation.

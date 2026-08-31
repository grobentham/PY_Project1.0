# XAU V16 R7-R1 — Full Runtime Repair

## Status

R7-R1 is an operational runtime repair around the frozen V16 R6 strategy package.

It does **not** retune R6 and it does **not** access Final Holdout outcomes.

Real/live account execution is prohibited. Demo order sending is disabled by default.

## Requirements

- Windows 10/11
- Python 3.9 or newer
- MetaTrader 5 desktop terminal
- Blueberry Markets demo account logged in
- account currency SGD
- broker symbol `XAUUSD.i`
- Python package `MetaTrader5` for connected MT5 operations

Offline software/integrity status does not require MetaTrader 5 connectivity.

## Start

Run only:

`START_XAU.bat`

The launcher provides:

1. Offline software + package-integrity status
2. MT5 account/quote/exposure status
3. Crash-recovery reconciliation
4. R6-derived intent preflight with **no send**
5. Explicitly unlocked demo submission
6. Preserved original R6 launcher
7. Exit

## Frozen risk enforcement

R7-R1 enforces:

- 0.55% operating projected-stop risk cap
- 0.60% constitutional projected-stop risk ceiling
- S$850 projected-equity floor
- maximum 0.02 canonical lot
- one XAUUSD.i exposure domain at a time, including pending orders
- `AUX_RF_LTM` rejected
- martingale OFF
- recovery OFF
- averaging down OFF
- pyramiding OFF
- loss-contingent sizing OFF

Projected stop risk is calculated from the current executable MT5 quote to the broker stop using MT5 `order_calc_profit()`, plus the frozen protected-validation round-turn commission burden of S$0.0945 per 0.01 lot. The caller cannot supply its own projected-loss number.

## Demo execution lock

`order_send()` cannot be reached unless all of the following are true:

- package integrity passes
- Blueberry server identity passes
- server is a demo server
- account currency is SGD
- `XAUUSD.i` is available
- MT5 trading permissions are enabled
- quote/spread guards pass
- no existing XAUUSD.i position or pending order exists
- broker volume/stops geometry passes
- broker-derived frozen risk gates pass
- `order_check()` passes
- a second immediately-before-send preflight also passes
- `R7_R1_RUNTIME_CONFIG.json` contains `"request_demo_execution": true`
- environment variable `XAU_R7_R1_ENABLE_DEMO_EXECUTION` exactly equals `YES_I_ACCEPT_DEMO_ONLY`

The default configuration keeps demo submission locked.

## Intent JSON boundary

R7-R1 deliberately does not fabricate a live strategy feed from the research/backtest engine. Until a separately audited causal R6 live-signal adapter exists, the execution boundary accepts an explicit intent JSON containing only:

```json
{
  "client_intent_id": "unique_id",
  "side": "BUY",
  "lot": 0.01,
  "stop_price": 2999.0,
  "take_profit_price": 3002.0,
  "source": "BASE"
}
```

Prices above are examples only, not trading instructions.

The runtime derives the executable entry price, projected stop loss, risk percentage and broker request itself.

## Crash and duplicate behavior

- Intent payloads are stored transactionally in SQLite WAL mode with `synchronous=FULL`.
- Reusing an intent ID with a changed payload is an idempotency collision and fails closed.
- The broker is checked for the same R7-R1 magic/comment before a new intent proceeds.
- Runtime persists `SUBMITTING` before `order_send()`.
- After a crash, `SUBMITTING`/`SUBMITTED` intents are reconciled against MT5.
- Ambiguous states become `MANUAL_REVIEW_NO_RESUBMIT`.
- R7-R1 never automatically resubmits an ambiguous order.

## Integrity behavior

Every R7-R1 invocation verifies before creating mutable state:

- canonical R6 parent authority recorded by the builder
- every inherited R6 file except the deliberate top-level launcher replacement
- protected R6 strategy/policy files
- preserved original R6 launcher bytes
- R7-R1 runtime Python files
- replacement `START_XAU.bat`

The final ZIP is also compiled, unit-tested and integrity-checked again after clean extraction by `BUILD_R7_R1.ps1` before the builder reports PASS.

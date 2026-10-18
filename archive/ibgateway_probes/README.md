One-off IB Gateway probes / diagnose helpers moved out of `deploy/ibgateway/` (Phase I cleanup).

Active ops stay in `deploy/ibgateway/`: gateway-health, status/check_bot, login helpers, live-worker + picker-rank timers, install/harden scripts, and still-used probes (`probe_us_bars.py`, `probe_buying_power.py`).

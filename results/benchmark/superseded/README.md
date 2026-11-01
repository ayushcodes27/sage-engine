# Superseded benchmark runs

Not used for any reported number. Kept so the history of the measurement is visible.

## bench-final-67abc76b (commit 1c31e34)

After each repetition the script waited a fixed 1 s before scraping the gateway timers. At concurrency 32
the ML service had a backlog (mean ML round trip ≈ 0.5 s), so async scores were still in flight at the
scrape: e.g. async c=32 rep 2 recorded 118 completed ML calls against ~192 in the other repetitions, and
the unfinished work spilled CPU load into the next repetition. Fixed by waiting until the ML round-trip
and Kafka publish timer counts are stable for 3 s (`drain()` in `load-tests/benchmark_gateway_overhead.py`),
then the full benchmark was re-run.

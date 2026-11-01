# Superseded benchmark runs

Not used for any reported number. Kept so the history of the measurement is visible.

## bench-final-67abc76b (commit 1c31e34)

After each repetition the script waited a fixed 1 s before scraping the gateway timers. At concurrency 32
the ML service had a backlog (mean ML round trip ≈ 0.5 s), so async scores were still in flight at the
scrape: e.g. async c=32 rep 2 recorded 118 completed ML calls against ~192 in the other repetitions, and
the unfinished work spilled CPU load into the next repetition. Fixed by waiting until the ML round-trip
and Kafka publish timer counts are stable for 3 s (`drain()` in `load-tests/benchmark_gateway_overhead.py`),
then the full benchmark was re-run.

## bench-final-5451bd12 (commit 30f5fec) — incomplete, retry storm

Interrupted during async mode when the Claude Code session ended (no summary.json / repetitions.json;
console.log has the completed repetitions). It exposed a gateway defect: at async c=32 only 26 and 8
ML calls completed for 32 clients (about 192 needed). `service_log_counts.txt` shows the inference
service receiving 664 + 210 POST /predict in those minutes while the gateway logged 855 timeouts in one
minute. Cause: a client without a cached decision was re-scored on every request after a failed (1 s
timeout) attempt, and the timed-out HTTP exchange was not cancelled, so the retries kept the inference
service saturated and almost every attempt timed out (metastable overload; the first run stayed just
below the tipping point). Fixed by a per-client failure cooldown (`sage.ml.failure-cooldown-ms`,
default 5000) and cancelling timed-out requests in `MLInferenceFilter`; regression tests in
`MLInferenceFilterTest` (timeoutStartsCooldown, cooldownSuppressesRetries, probeOverridesCooldown).

# B2 — gateway overhead benchmark

**Canonical run: `bench-final-1971425f`** (git `18f2d9b`, clean tree, 2026-11-01 23:38–23:49 +0530).
Produced by `load-tests/benchmark_gateway_overhead.py --label final` (defaults: modes off, features, async,
sync; concurrency 1, 8, 32; 3 repetitions; 200 requests per worker; 20 ms think time). Earlier runs are in
`superseded/` with the reason each was replaced; none is used for any reported number.

Files: `summary.json` (per-cell medians over repetitions, overhead vs `off`, R7), `repetitions.json`
(every repetition, incl. gateway timer deltas, ML attempts by result, per-container CPU/memory), `raw/`
(per-request latencies `*.csv.gz` with SHA-256 in `repetitions.json`, `docker stats` samples). Host,
container image ids and app.jar SHA-256 are in `summary.json -> meta`.

## Pre-registered gate R7 (`configs/gates_revised_v1.json`, committed in bffaa2e before any run)

`r7_observed_ms` = max over concurrency of p95(async) − p95(off) = **52.07 ms** (at c = 8) against a
limit of 50 ms → **FAIL**. Not re-tuned. The superseded first run measured 47.9 ms, i.e. the result is
near the limit and varies run to run; only the canonical run is reported.

## Conditions and limitations (read before citing numbers)

- Single host: the load generator, gateway, Redis, Kafka, inference service (4 uvicorn workers) and mock
  site share one laptop (i5-13420H, 12 threads, 15 GiB), CPU governor `powersave` (not changeable without
  root). The inference service reaches several hundred % CPU at c = 8 and 32, so the async p95 overhead
  includes CPU contention with scoring work that is off the request path in a multi-host deployment; the
  benchmark cannot separate the two. The median (p50) overhead of async vs off is 3–4 ms at every level.
- The mock site adds unseeded 5–20 ms per response (audit N21); all modes share it.
- Closed-loop load, one client IP per worker; mix 3 non-static : 1 static; every worker passes the
  scoring gate and is re-scored every 20 non-static requests.
- ML call counts: use `internal.ml_attempts` (every attempt by result) or the ML round-trip timer
  count. The `ml_outcomes` counter labels async re-scores of an already-cached client `Cached`.
  The number of scores per repetition follows from when each client's 3 s duration gate opens;
  replaying the gate over the recorded client-side request times reproduces the counts within ±3 for
  every repetition without timeouts.
- Overload: at c = 32 up to 21 ML calls per repetition time out (1 s). After a failed score the
  client is not re-scored for 5 s (`sage.ml.failure-cooldown-ms`), so those repetitions have fewer
  scores (e.g. async c=32 rep 1: 139 scored + 19 timeouts). Without this cooldown the gateway entered a
  retry storm in which almost every attempt timed out (`superseded/README.md`).

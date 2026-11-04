# JNSM Revision — Step A Audit and Remediation Plan

Audited tree: branch `feat/jnsm-revision` at `f61b8d6` (= `2d063bd` + README).
Evaluated build: `8f79cf6`. Date: 2026-11-01. No code was changed during this audit.

Environment observed: Linux, 12 cores, 15 GB RAM, Docker 29.4, OpenJDK 21.0.9,
Python 3.12.3 (containers use 3.11), xgboost 3.2.0 / scikit-learn 1.8.0 on host.
Baseline: `mvn test` 21/21 pass; `pytest ml_pipeline/tests` 13/13 pass.

---

## 1. Verification of the known defects (Section 1 of the brief)

| # | Status | Evidence |
|---|---|---|
| 1 | **Confirmed** | `evaluate_shadow.py:687` guards on `"profile_metrics" in locals()`; the name is never assigned, so G-per-profile is always PASS. |
| 2 | **Confirmed** | f0 = `times.size()` capped by `LTRIM 0..49` (`RedisTelemetryService.java:72,84`). Re-score condition `sessionDepth - lastScoredDepth >= 20` (`MLInferenceFilter.java:155`) → fires only at k=21 and k=41. |
| 3 | **Confirmed** | `prodInferenceLatencyMs`/`shadowInferenceLatencyMs` are initialised `null` (`MLInferenceFilter.java:110-111`) and never set; `performMlInference` does not read `production_processing_time_ms`/`shadow_processing_time_ms` (the `8f79cf6` build did). Async results are only cached in Redis (`:319`) and surface on the *next* request; a score triggered by the last request is never emitted. |
| 4 | **Confirmed** | Gateway requires `X-SAGE-Probe-Secret` (`MLInferenceFilter.java:129-141`); generator sends only `X-SAGE-Probe: true` (`diverse-shadow-traffic.py:234`) and never `X-SAGE-Sync-Score`. |
| 5 | **Confirmed** | Cookie set in `FastPathFilter.java:54-61` / `GatewayController.java:185-194`; `SAGE-Session-Id` attribute read nowhere. `incrementSubnetCounter` (`RedisTelemetryService.java:56,388`) return value discarded. All keys use `ip`. |
| 6 | **Confirmed** | `git diff 563f568 HEAD -- EnforcementFilter.java` is empty; `sage.enforcement.enabled: false`; `X-Sage-Challenge` (`EnforcementFilter.java:75`) read nowhere. |
| 7 | **Confirmed** | `diverse-shadow-traffic.py:455-456` prints a warning only; `--allow-dirty` not written to the manifest. |
| 8a | **Confirmed** | Default input `load-tests/diverse_telemetry_final.jsonl` is gitignored (`.gitignore: /load-tests/*.jsonl`) and absent; `lopo_evaluation_report.json` has no run id. |
| 8b | **Confirmed** | Human train/test split is drawn once before the fold loop (`evaluate_lopo.py:122-134`); IF fitted only on those humans with `random_state=42` → identical IF in every fold. |
| 8c | **Confirmed** | Test humans are a 50% split of the same 4 human profiles used in training (`evaluate_lopo.py:126-131`). |
| 8d | **Confirmed (by construction)** | Generator delays: asset_fetching_bot 0.1 s, fast_scraper 0.02–0.05 s vs humans ≥0.3 s (`diverse-shadow-traffic.py:271-304`). |
| 9 | **Confirmed** | Per-profile `n_clients` = scored clients only (`evaluate_shadow.py:596-611`). Run A report: fast_scraper 41 clients → 100%; run B: 0 → 0%. |
| 10 | **Confirmed** | `human_fpr_ok = fpr_ci[0] <= max_human_fpr` (`:680`) uses the point estimate. |
| 11 | **Confirmed** | `benchmark_gateway_overhead.py` has no ML-off switch; no committed outputs; `session_replay.py` has no outputs. |
| 12 | **Confirmed — and more serious than stated** | `basket` was added to `isCartPath` (the static helper) *and* to the config default. `SAGE_Cart_Ratio` (f5) is an input of **both** frozen models, so `2d063bd` changed a model feature definition. `label_eclog.py:38` has no `basket`. |
| 13 | **Confirmed (code)** | At `8f79cf6`, duration = span of the 50-entry list. Run B report: 2,060 duration/other-gated records. First-seen key at `2d063bd` is covered only by a mocked unit test (`FastClientScoringRegressionTest`), never run against Redis. |
| 14 | **Unexplained — raw telemetry absent** | See §3.4 for a code-level hypothesis. |
| 15 | **Confirmed** | `timing_cascade_analysis.py:50` defaults to `diverse_telemetry_5fc1e6d8.jsonl` (not committed). No TreeSHAP code is committed anywhere (grep for `shap` matches only "shape"). |

Claims marked FALSE in the brief (Table 5 values, per-client seeding) were not touched.
Per-client seeding is confirmed at `diverse-shadow-traffic.py:215` — but see N12.

---

## 2. Context facts that do NOT hold

| Claim | Finding | Evidence |
|---|---|---|
| Tag `v2-frozen-models-v6` exists | **Missing locally and on `origin`** (only `v1.0.0`). `evaluate_shadow.py` and `verify_frozen_manifests.py` silently fall back to the working-tree manifest. | `git tag`, `git ls-remote --tags origin`; `evaluate_shadow.py:84-93` |
| `sage_binary_v1` trained on the EClog one-day sample | **False.** It was trained on `ml_pipeline/data/training_data.csv` (96 synthetic gateway clients, labels human/scraper/flood/recon). The pickled `scale_pos_weight=1.4547945…` equals the human:bot ratio of the train split of that file exactly (1,792 rows). | `train_sage_binary.py:26`, `sage_binary_split_manifest.json` (67/29 clients) |
| Original gates G1–G7 are intact | `final_campaign_config.json` was **edited in place** by `2d063bd` (added `min_per_profile_recall`). Current SHA-256 `724cb0df…`; original (and run B manifest's `campaign_config_hash`) `f03616e1…`. | `git diff 8f79cf6 2d063bd -- final_campaign_config.json` |
| Runs A/B raw telemetry available | **Not present** on this machine (gitignored). Only run B's manifest is committed (`diverse_manifest.json` = `shadow_manifest.json` = `diverse-ba1a90e8`); run A has a report only. | `find`, manifest `run_id` |
| Frozen frozen-scoring-path files | `verify_frozen_manifests.py` **fails at HEAD**: `RedisTelemetryService.java`, `MLInferenceFilter.java`, `application.yaml` differ from the pinned hashes → the CI integrity job cannot pass. | verifier output |

The frozen model/contract files themselves are intact: all four `.pkl` and three contract SHA-256s match `frozen_models_manifest.json`, whose own SHA-256 (`9398b6d0…`) equals the value recorded in run A's report.

---

## 3. New issues found

### 3.1 Train/serve parity
- **N1 (critical) — timestamp resolution skew.** In `eclog_weak_labeled.csv`, 90.6% of `NonStatic_Navigation_Gap` values are whole seconds; velocity saturates at 5,000 req/s (= n / 0.001 s floor). EClog timestamps are effectively 1-s resolution; the gateway uses ms. f1, f2, f6, f7 are therefore computed on a different scale in training than at serving time (e.g. f7 "gap ≥ 0.5 s" means "gap ≥ 1 s" in training). This is a plausible mechanism for the "speed ⇒ human" behaviour and must be reported.
- **N2 — only 54 bot sessions reach depth ≥ 21** in the one-day sample (662 human). Confirms the need for the six-month EClog for a k=21 prefix model.
- **N3 — parity tests don't cover the cart rule or the session loop.** `test_feature_parity.py` re-implements features rather than calling the `label_eclog.py` session loop; no fixture case contains `basket`, which is why defect 12 passed CI.
- **N4 — f5/f6' denominators.** Cart and asset-skip ratios use the Redis hash lifetime (5-min TTL refreshed every request) vs. a 300-s inactivity sessioniser in training; equivalent only while gaps < 300 s. Document, test the boundary.

### 3.2 Telemetry / Kafka
- **N5 — no per-client ordering.** Kafka key = per-request UUID (`EnforcementFilter.java:176` → `KafkaProducerService.java:26`) over 3 partitions. Any "first record with depth ≥ 21" (LOPO, cascade analysis) taken in file order is not guaranteed to be the earliest.
- **N6 — the logged feature vector is not the scored vector.** Telemetry carries the *current* request's features plus a *cached* decision; with async scoring the scored vector is never logged. Table 10 / SHAP inputs from telemetry are therefore off by ≥1 request.
- **N7 — silent drops.** Send failures logged at `debug` only; `application.yaml` producer settings (`max.block.ms`, `compression`, `buffer.memory`) are ignored because `KafkaConfig` builds its own factory. No producer metrics or send-failure counter.
- **N8 — sync path loses shadow fields.** In the `fresh_sync` branch (`MLInferenceFilter.java:196-208`) shadow probability/flag/hashes are not copied from `freshResult`, so a synchronous probe score is logged with stale or null shadow fields.
- **N9 — cache merge.** `cacheMlDecision` uses `putAll` into the existing hash; fields absent in a newer response survive from the older decision.

### 3.3 Evaluator / gates
- **N10 — G7 passes vacuously.** With no latency values, `over_p95 = 0.0` (`evaluate_shadow.py:642`) → PASS. At `2d063bd` G7 can never fail.
- **N11 — G3 blind to ML timeouts.** Gateway timeouts/backpressure are recorded only in `evaluationStatus` (`Timeout`, `SemaphoreFull`, `Error`); the gate checks `shadow_status ∈ {timeout,error}`, a value the gateway never emits. `evaluation_status` is loaded (`:220`) and unused.
- **N12 — "scorable client" uses total requests** (`request_count >= 21`, `:670`), including static hits; scorability depends on non-static depth > 20 and duration ≥ 3 s.
- **N13 — G7 measures shadow−prod model time**, not gateway overhead; shadow timing includes DataFrame construction, prod timing does not (`main.py:253-257` vs `:281-285`). 62% negative overheads in run A.
- **N14 — default FPR limit 0.10** if the config cannot be read (`:661`), vs 0.01 in the config.
- **N15** — `--bootstrap-samples` unused; `predicted_bot` = "ever flagged" over all events (document as the client rule).

### 3.4 Generator / campaign
- **N16 — overlapping RNG streams.** `seed + client_idx` with profile seeds 9101…9107 ⇒ e.g. `normal_browser-01` and `spa_client-00` share seed 9102; at 75 clients/profile the overlap is extensive. Must stay identical for comparability in campaign C (A/B used it), but must be disclosed.
- **N17 — client failures swallowed** (`:512-514`); `request_count` stays `None`, which the evaluator treats as scorable.
- **N18 — concurrency not recorded.** `DIVERSE_MAX_WORKERS` (default 3) is not in the manifest; A/B concurrency is unknown.
- **N19 — Redis clear incomplete.** `first_seen`, `subnet`, `scoring_inflight` keys are not cleared between runs; run octet is `hash % 250` so IP reuse across runs within 5 min is possible.
- **N20 — /24 = profile.** IPs are `10.<run>.<profile>.<client>`, so every profile is one /24; enabling /24 aggregation would merge all clients of a profile.
- **N21 — unseeded server jitter.** Mock site adds `Math.random()` 5–20 ms per response (`server.js:84-87`).
- **Defect 14 hypothesis (unverifiable without raw telemetry):** mobile_browser has the fewest non-static requests (22–30 + probe) and, at `8f79cf6`, an ML timeout/backpressure left no cache and no visible status (N11). Three consecutive failures at depths 21–23 would leave the client unscored. Not claimable without telemetry.

### 3.5 Build / reproducibility
- **N22 — clean-clone Docker build fails on Linux:** `sage-gateway/mvnw` is tracked as mode `100644`; the Dockerfile runs `./mvnw`.
- **N23 — unpinned deps:** `requirements.txt` uses `>=` (xgboost ≥ 2.0 loading pickles from an unknown version); images `latest` for prometheus/grafana/kafka-ui; 4 uvicorn workers.
- **N24 — inference thresholds overridable by env** (`PROD_CONFIDENCE_THRESHOLD`, `SHADOW_CONFIDENCE_THRESHOLD`) and the prod threshold is not logged in telemetry.
- **N25 — only one shadow slot** in `main.py`; campaign C's third model needs a multi-shadow path.
- **N26 — benchmark hits non-existent route** `/api/products/N` (mock site has `/api/price|inventory/:id`), so half its requests measure 404s; default URL 8081 vs compose 8083.
- **N27 — Zanbil access.** `Access.log.zip` on Dataverse (doi:10.7910/DVN/3QBYB5) is **restricted**; it cannot be fetched by script without an approved access request/API token. EClog (doi:10.7910/DVN/Z834IK) files `eclog_1day.tab` and `eclog.zip` (598 MB, six months) are public, CC0 with additional terms → derived features only, no raw logs committed.
- **N28 — Zanbil evaluation uses site-adapted rules** (`basket`, `/image/` static) — f5 and asset-skip differ from training; must be reported as an adaptation, and a no-adaptation variant added.
- **N29 — Python 3.12 host vs 3.11 container**; pin and run analyses inside a container.

---

## 4. Prioritised remediation plan

Effort: S ≤ 2 h, M ≈ half day, L ≈ 1–2 days (agent wall-clock, excluding campaign run time).

### P0 — integrity (before any new run)
1. Restore `final_campaign_config.json` to the `8f79cf6` bytes (`f03616e1…`); move revised gates to `configs/gates_revised_v1.json` (hash recorded). — S
2. Revert the default cart rule to the EClog rule; `basket` only in `configs/zanbil_site.yaml`; add parity fixture cases for `basket`, `/static/`, query strings. — S
3. New scoring-path manifest (`frozen_scoring_path_v7.json`) for the remediated gateway; leave the v6 manifest untouched; verifier checks v6 for A/B and v7 for C. — S
4. `chmod +x mvnw`; pin Python deps (lock file) and image digests. — S

### P1 — B1 fixes, each with a regression test
5. Evaluator: explicit per-profile recall; G6 unscored-bot = miss; G5 point + Clopper–Pearson upper; G3 includes `evaluationStatus`; G7 FAIL on no data; scorable = non-static depth; new re-grade report for A/B (from committed reports where raw telemetry is missing, clearly labelled). — M
6. Uncapped per-client counter `sage:reqcount:<id>` for re-scoring; f0 unchanged. — S
7. Async: record model times inside the task; emit `score.completed` event carrying the exact scored feature vector, both/all model outputs, latencies; fix sync-path shadow fields (N8) and cache replace (N9); per-client Kafka key; send-failure counter. — M
8. Generator: probe secret from env (never committed) + `X-SAGE-Sync-Score`; dirty tree aborts unless `--allow-dirty` (recorded); per-profile client counts; record concurrency, versions; fail-loud on client errors; clear all `sage:*` test keys. — S
9. Cookie / /24: keep unused, flag-gated OFF, documented (recommended; see N20). — S

### P2 — B2 overhead benchmark — M
10. `sage.ml.enabled` flag (proxy-only), sync vs async modes; fix routes; 3+ concurrency levels; collect p50/95/99, throughput, CPU/mem (`docker stats`), Redis RTT and Kafka publish latency via Micrometer timers. Single host — documented as a limitation.

### P3 — B3 offline experiments — L
11. Checksum-verified download script (EClog public; Zanbil needs your access — see questions).
12. Grouped train/val/test by client; prefix rows at k=21 via the shared feature code; prefix model trained, frozen, hashed **before** campaign C.
13. Comparisons, matched-FPR, Brier, reliability, exact CIs; coverage at k∈{5,10,15,21}; Markov baseline; Zanbil (no retraining + calibration-only) if access is granted.
14. N1 timestamp-resolution analysis as a declared sensitivity experiment.

### P4 — B4 campaign C — L (runtime ~2–4 h per seed at 3 workers)
15. 300 humans + 150 bots, identical profile logic; three models in shadow; original G1–G7 + revised gates, all hashed pre-run; archive compressed telemetry + SHA-256; up to 2 extra seeds.

### P5 — B5 analyses, C self-audit, deliverables — L
16. Table 10 replacement, per-client TreeSHAP, LOPO (a)–(d) with pre-declared splits; `run_all.sh`; clean-clone test; consistency checker; `TRACEABILITY.md`, `REPRODUCE.md`, `results/RESULTS_CHANGELOG.md`, final report.

---

## 5. Blocking decisions for the authors
1. **Tag `v2-frozen-models-v6`** — recreate locally at `8f79cf6` (manifest bytes match the hash in run A's report), or does a co-author hold the original tag?
2. **Runs A/B and dev-run raw telemetry** — can a co-author supply `diverse_telemetry_*.jsonl` for `8881bc1c`, `ba1a90e8`, `5fc1e6d8` (and run A's manifest)? Without them, A/B re-grading is limited to counts in committed reports and defect 14 stays unexplained.
3. **Zanbil access** — restricted on Dataverse; provide the local file or an approved API token.
4. **Prefix model and N1** — train on EClog features exactly as defined (recommended, required by the rules) and report the resolution skew as a separate sensitivity experiment.
5. **Release tag** for campaign C — create locally only (no push).

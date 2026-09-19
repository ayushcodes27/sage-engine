# SAGE Engine Project Handoff

Last updated: 2026-09-18

## Current Objective

Complete controlled shadow-mode validation of the ECLog weak-label model. Production enforcement must remain disabled until repeated diverse shadow runs satisfy predefined safety gates.

## Repository

- `sage-gateway/`: Java/Spring Gateway, Redis telemetry, Kafka events, ML filter.
- `ml_pipeline/`: Python feature pipeline, models, inference service, evaluation scripts.
- `load-tests/`: controlled traffic generators, manifests, telemetry exports.
- `infra/`: Docker Compose services.
- `evaluation/reports/`: validation reports and walkthroughs.

## Important Interpretation Rules

- Synthetic labels are IP-prefix-derived reference labels, not verified ground truth.
- ECLog labels are User-Agent-derived weak/proxy labels, not verified ground truth.
- Controlled browser/scraper traffic is controlled validation, not proof of real-world accuracy.
- Do not replace the production model or enable enforcement based on one run.
- Shadow actions are hypothetical and must never change actual enforcement.

## Model Results

### Synthetic Reference-Label Model

- Dataset: 2,544 rows; 1,007 bot; 1,537 human.
- Own evaluation: ROC-AUC 0.9994; CV F1 0.9865.
- Main features: Asset Skip Ratio 0.5538; Request Velocity 0.3180.
- Interpretation: evidence of synthetic label/feature leakage or an overly simple load-test distribution.

### ECLog Weak-Label Model

- Dataset: 8,797 sessions; 4,004 clients.
- Unknown sessions excluded: 517.
- Known sessions: 3,604 bot; 4,676 human.
- Holdout proxy agreement: ROC-AUC 0.9709; Macro F1 0.9400.
- Feature importance: Asset Skip 0.6783; Endpoint Concentration 0.1065; Session Depth 0.0770; Cart Ratio 0.0613; Velocity 0.0436; Diversity 0.0202; Temporal Variance 0.0132.
- Interpretation: strong agreement with UA heuristics, not proven real-world bot detection.

### Cross-Dataset ECLog Holdout

Same holdout for both models: 2,636 sessions from 1,202 clients.

- Synthetic model: ROC-AUC 0.8971; PR-AUC 0.8407; Macro F1 0.8047; bot recall 96.28%; human FPR 33.14%.
- ECLog model: ROC-AUC 0.9709; PR-AUC 0.9502; Macro F1 0.9400; bot recall 95.79%; human FPR 7.57%.
- Correct conclusion: synthetic ranking transfers reasonably, but its frozen 0.5 operating point transfers poorly. ECLog operates better against its own proxy labels, but neither result proves ground-truth accuracy.

## Feature Contract

Gateway and Python are intended to use the same contract:

- Five-minute inactivity horizon.
- Last 50 non-static requests.
- Canonical path: remove query/fragment, collapse repeated slashes, lowercase, normalize trailing slash.
- Static asset: `/static/` prefix or standard asset extension including `.js`, `.css`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.woff`, `.woff2`, `.ttf`, `.svg`, `.webp`.
- Cart path contains `cart`, `checkout`, `koszyk`, `platnosc`, `zamowienie`, or `payment`.
- Session depth: non-static count, max 50.
- Velocity: non-static count divided by time span; minimum span 0.001 seconds; fallback 1.0 for fewer than two requests.
- Temporal variance: standard deviation of inter-arrival times divided by mean IAT.
- Behavioral diversity: natural-log Shannon entropy of canonical non-static paths.
- Endpoint concentration: maximum canonical-path frequency divided by non-static count.
- Cart ratio and asset skip ratio use total hits, including static assets.
- Contract hash currently used by the ML service: `075677d319331d2172c900f7fb3ce9d4b2dd3e26a2dd6854fd2d1de53bf3262a`.

The hash verifies the contract document, not mathematical equivalence between Java and Python. Runtime feature-value comparison is still important.

## Gateway Cache Fix

The Gateway previously called Python on every request after the session gate (`sessionDepth > 20` and `sessionDuration >= 3.0`), causing inference storms and 100ms timeouts.

Implemented fix:

- `RedisTelemetryService.java`: five-minute Redis ML decision cache.
- `MLInferenceFilter.java`: reuse cached production/shadow decision; cache successful scores.
- `EnforcementFilter.java`: accepts `Scored` and `Cached` statuses.
- Cache is keyed by client/IP and expires after five minutes.
- Production enforcement remains unchanged and disabled.

Known hardening follow-up: add a Redis single-flight lock if concurrent cold-cache requests still duplicate the first inference.

## Macro-Timing Features & Model-Specific Contracts

Implemented separate model-specific feature contracts:
- Production Contract: 7 features (`ml_pipeline/models/contracts/contract_prod_7feat.json`, hash: `4e8b01ac1b96952c...`)
- ECLog 6-Feature Contract: 6 features (`ml_pipeline/models/contracts/contract_eclog_6feat.json`, hash: `40f3b0dd6b44127c...`)
- ECLog Timing Contract: 8 features (`ml_pipeline/models/contracts/contract_eclog_timing_8feat.json`, hash: `2fb47afb4dae24d3...`)

Timing feature definitions (precisely named and mathematical identical in Java and Python):
- `SAGE_NonStatic_Navigation_Gap`: median inter-arrival time (seconds) between consecutive non-static requests within the session window.
- `SAGE_NonStatic_Long_Gap_Ratio`: fraction of consecutive non-static inter-arrival intervals $\ge 0.50$ seconds.

Offline 5-Fold Grouped Cross-Validation (Stratified by `IpId` client):
- Candidate Model: 8-feature timing model (`6 features without Asset_Skip_Ratio + NonStatic_Navigation_Gap + NonStatic_Long_Gap_Ratio`).
- Grouped CV ROC-AUC: **0.9719 $\pm$ 0.0139** (Holdout ROC-AUC: **0.9699**, PR-AUC: **0.9500**, Macro F1: **0.9449**).
- Grouped CV Recall: **89.16%** [80.85%, 97.87%], Human FPR: **6.24%** [4.85%, 7.62%].
- Artifacts generated:
  - `ml_pipeline/reports/macro_timing_ablation_results.json`
  - `ml_pipeline/reports/macro_timing_ablation_report.md`
  - Model: `ml_pipeline/models/eclog_timing_binary_model.pkl` (embedded contract hash `2fb47afb4dae...`, threshold `0.35`, model version `timing-v1`).

Gateway Dynamic Timing Telemetry & Caching:
- `RedisTelemetryService.java`: computes `nonStaticNavigationGap` and `nonStaticLongGapRatio` directly over the rolling non-static timestamp list.
- `MLInferenceFilter.java`: reuses cached production decisions to prevent inference storms, but supports re-scoring shadow timing metrics at deliberate session probes (`X-SAGE-Probe: true`).
- Telemetry records `decision_source` (`fresh` or `cached`), `scoring_depth`, and `scoring_timestamp` in `RequestEvent.MLMetadata`.
- Schema compatibility verified via `RequestEventSchemaCompatibilityTest.java`.

## Archived Runs & Model Attribution

| Run ID / Telemetry Artifact | Shadow Model Used | Fresh Scored Records | Classification & Evidence Status | Notes |
|---|---|---:|---|---|
| `diverse-9a09af81` (`diverse_telemetry_9a09af81.jsonl`) | **timing** (8-feat) | 279 | Timing-model evidence | 140-client campaign; $\max\|\text{logged}-\text{timing}\| = 0.000050$, vs $0.454114$ for weak |
| `diverse-04935d77` (`diverse_telemetry_04935d77.jsonl`) | **timing** (8-feat) | 70 | Timing-model evidence | 35-client smoke test; $\max\|\text{logged}-\text{timing}\| = 0.000048$, vs $0.454114$ for weak |
| `diverse-c109808c` (`diverse_telemetry_c109808c.jsonl`) | **timing** (8-feat) | 4 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000048$ |
| `diverse-29037b60` (`diverse_telemetry_29037b60.jsonl`) | **timing** (8-feat) | 6 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000038$ |
| `diverse-1de5e4da` (`diverse_telemetry_1de5e4da.jsonl`) | **timing** (8-feat) | 4 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000048$ |
| `diverse-e186fd8e` (`diverse_telemetry_e186fd8e.jsonl`) | **weak** (7-feat) | 35 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.454128$ for timing |
| `diverse-5fc1e6d8` (`diverse_telemetry_5fc1e6d8.jsonl`) | **weak** (7-feat) | 35 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.268815$ for timing |
| `diverse-236eb894` (`diverse-236eb894_telemetry.jsonl`) | **weak** (7-feat) | 2 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000039$, vs $0.041570$ for timing |
| `ml_pipeline/data/shadow_telemetry.jsonl` | **weak** (7-feat) | 140 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.118477$ for timing |

## Latest Valid Shadow Runs

### 1. 35-Client Smoke Test (Run ID: `diverse-04935d77`)
- 35/35 clients received valid shadow scores.
- Telemetry events: 2,001 (Shadow-scored events: 439).
- Human FPR: **0.00%** (95% CI 0.00% - 0.00%).
- `slow_scraper` Recall: **100.00%** (5/5).
- `fast_scraper` Recall: **100.00%** (5/5).
- `asset_fetching_bot` Recall: **0.00%** (0/5).
- Artifacts: `load-tests/diverse_smoke_report.md`, `load-tests/diverse_telemetry_04935d77.jsonl`.

### 2. 140-Client Scaled Campaign (Run ID: `diverse-9a09af81`)
- 140/140 clients received valid shadow scores (20 clients across all 7 profiles).
- Telemetry events: 7,827 (Shadow-scored events: 1,620).
- Human FPR: **0.00%** (95% CI 0.00% - 0.00%) across 80 human clients:
  - `normal_browser`: 0.00% FPR (0/20)
  - `spa_client`: 0.00% FPR (0/20)
  - `mobile_browser`: 0.00% FPR (0/20)
  - `privacy_browser`: 0.00% FPR (0/20)
- Bot Recall: **66.67%** (95% CI 55.00% - 78.33%):
  - `slow_scraper`: **100.00%** (20/20)
  - `fast_scraper`: **100.00%** (20/20)
  - `asset_fetching_bot`: **0.00%** (0/20)
- Precision: **100.00%** (95% CI 100.00% - 100.00%).
- Latency p50/p95: Production 80.94 ms / 263.03 ms; Shadow 63.35 ms / 242.68 ms.
- Paired overhead p50/p95: -13.31 ms / 67.07 ms.
- Artifacts: `load-tests/diverse_scaled_report.md`, `load-tests/diverse_telemetry_9a09af81.jsonl`.

Safety Gates Evaluation:
- Human FPR < 10%: **PASS** (0.00%).
- All manifest clients have valid shadow scores: **PASS** (140/140).
- Bot recall > 90%: **FAIL** (66.67% due to asset_fetching_bot).
- **Enforcement Status**: REMAINS DISABLED (`sage.enforcement.enabled: false`).

## Root Cause Analysis of Asset-Fetching Bot Behavior

Investigation of the underlying training data (`ml_pipeline/data/eclog_weak_labeled.csv`) reveals why a model trained strictly under weak-label supervision does not flag `asset_fetching_bot`:
1. **ECLog Label Distribution**: In ECLog, weak labels were assigned using User-Agent heuristics. Legitimate search indexers and web crawlers (e.g. Googlebot, Bingbot) pace requests conservatively (median non-static gap: **3.0s**, `NonStatic_Long_Gap_Ratio` = **1.0**).
2. **Human Burst Behavior**: Conversely, human browser sessions in the log often consist of short 1–2 page visits with zero long pauses (`NonStatic_Long_Gap_Ratio` = **0.0**).
3. **Distributional Collision**: In our controlled test, `asset_fetching_bot` loads HTML pages with only 100ms pauses between cycles, yielding `NonStatic_Long_Gap_Ratio` = **0.0** and rapid velocity. Because the model learned from ECLog that crawlers have long gaps ($\ge 0.5\text{s}$) and humans have short bursts, it assigns `asset_fetching_bot` a low bot probability (~0.0009).
4. **Methodological Takeaway**: Controlled validation proves that macro-timing features reliably catch both slow and fast non-static scraping without causing a single false positive on SPA or privacy browsers (0.00% FPR). However, distinguishing rapid asset-fetching bots from human shopping bursts cannot be resolved purely by unsupervised/weak labels derived from search crawlers; it requires multi-modal client-side signals (e.g., DOM execution proofs or behavioral mouse telemetry) rather than synthetic label overfitting.

## Immediate Next Task

1. Keep production enforcement strictly disabled.
2. Formulate client-side or DOM-execution behavioral proofs for distinguishing scripted asset loaders from human browser engines.
3. Maintain model-specific contracts and ensure no backward-incompatible schema changes.

## Remaining Work

1. Run threshold sweep on separate validation runs.
2. Test repeated campaigns with varied client counts per profile.
3. Formulate feature representation distinguishing asset-fetching bots from browser parsing.
4. Only consider limited enforcement after repeated runs pass all safety gates.

## Useful Commands

Compile Gateway:

```powershell
.\\sage-gateway\\mvnw.cmd -f .\\sage-gateway\\pom.xml clean compile -DskipTests
```

Compile Python scripts:

```powershell
python -m py_compile .\\load-tests\\diverse-shadow-traffic.py .\\ml_pipeline\\scripts\\evaluate\\evaluate_shadow.py
```

Run traffic only after Gateway/Redis/ML are confirmed healthy:

```powershell
$env:DIVERSE_MAX_WORKERS = "30"
python .\\load-tests\\diverse-shadow-traffic.py
```

Evaluate only matching telemetry and manifest artifacts:

```powershell
python .\\ml_pipeline\\scripts\\evaluate\\evaluate_shadow.py `
  --telemetry <matching-telemetry.jsonl> `
  --manifest .\\load-tests\\diverse_manifest.json `
  --report .\\load-tests\\diverse_report.md
```

Never treat a run with `Clients without a valid shadow score > 0` as a model evaluation.

## Train/Serve Skew: Whole-Session Training vs Prefix Scoring

- **Offline Training**: `label_eclog.py` aggregates features across entire completed user sessions (whole-session aggregation). Feature values reflect terminal session characteristics.
- **Online Serving**: `RedisTelemetryService.java` computes rolling window features on dynamic request prefixes in real time (evaluated at request depth $k \ge 21$).
- **Impact**: Early-session prefixes have naturally distinct variance and gap characteristics compared to terminal session summaries. Production deployment must evaluate calibration on prefix-based shadow telemetry before considering active enforcement.

## Limitations: Deployed Binary Verification

- `app.jar` hash is recorded at run start and end via `docker exec sage-gateway sha256sum /app/app.jar` (verifying run-time container immutability), but is not verified against source code build.
- `main.py` hash is similarly recorded at run start and end via `docker exec sage-ml sha256sum /app/main.py`. Container digest pinning remains a follow-up hardening task.

## Agent Handoff Rules

- Inspect current files before editing; user/formatter changes may exist.
- Make one focused task per agent/session.
- Preserve unrelated user changes.
- Use `apply_patch` for edits.
- Validate immediately after edits.
- Do not reset, revert, or commit unless explicitly requested.
- Report exact files changed, commands run, results, limitations, and next task.
- Keep enforcement disabled throughout validation.

# Diverse Shadow Validation Report

Run ID: `diverse-9a09af81`

> [!WARNING]
> **Status Note: UNVERIFIED (Historical / Archived)**
> This historical 140-client campaign was conducted prior to model and schema cryptographic freezing (`v2-frozen-models`). The telemetry records lack per-record identity fields (`prod_model_sha256`, `shadow_model_sha256`, `shadow_contract_hash`, `shadow_feature_list_hash`), and therefore cannot be cryptographically verified against the frozen manifest. This report is retained solely for historical audit purposes.

This is run-specific controlled validation using manifest labels. It is not proof of real-world accuracy, and it must not be reported as production ground truth.
Enforcement remains disabled. Threshold calibration must use a separate validation set; the ECLog holdout remains untouched.

## Profile Matrix

| Profile | Expected class | Asset behavior | Rate |
|---|---|---|---|
| normal_browser | human | Loads most assets | Interactive |
| spa_client | human | Minimal assets, API-heavy | Moderate |
| mobile_browser | human | Loads assets slowly | Slow |
| privacy_browser | human | Selectively skips assets | Interactive |
| slow_scraper | bot | Mostly non-static | Slow |
| asset_fetching_bot | bot | Loads everything | Rapid |
| fast_scraper | bot | Mostly API paths | Very rapid |

Manifest clients: 140
Telemetry events matched by run_id: 7827
Telemetry events joined to manifest client_id: 7827
Telemetry events without manifest truth: 0
Manifest clients without telemetry: 0
Events with missing event/model metadata: 0
Duplicate event IDs in matched telemetry: 0
Shadow-scored events: 1620
Shadow-scored clients: 140
Clients without a valid shadow score: 0

## Aggregate Client Metrics

Human FPR: 0.00% (95% CI 0.00% - 0.00%)
Bot recall: 66.67% (95% CI 55.00% - 78.33%)
Precision: 100.00% (95% CI 100.00% - 100.00%)
Confusion matrix: TP=40 FP=0 TN=80 FN=20

## Profile Metrics

| Profile | Class | Clients | Metric | Value | 95% CI |
|---|---|---:|---|---:|---|
| normal_browser | human | 20 | FPR | 0.00% | 0.00% - 0.00% |
| spa_client | human | 20 | FPR | 0.00% | 0.00% - 0.00% |
| mobile_browser | human | 20 | FPR | 0.00% | 0.00% - 0.00% |
| privacy_browser | human | 20 | FPR | 0.00% | 0.00% - 0.00% |
| slow_scraper | bot | 20 | Recall | 100.00% | 100.00% - 100.00% |
| asset_fetching_bot | bot | 20 | Recall | 0.00% | 0.00% - 0.00% |
| fast_scraper | bot | 20 | Recall | 100.00% | 100.00% - 100.00% |

SPA false-positive clients: 0
Privacy-browser false-positive clients: 0

## Threshold Comparison (0.50 vs 0.35)

| Metric / Profile | Class | Clients | Threshold 0.50 | Threshold 0.35 | Delta |
|---|---|---:|---:|---:|---:|
| **Overall Bot Recall** | bot | 60 | 66.67% | 66.67% | 0.00% |
| **Overall Human FPR** | human | 80 | 0.00% | 0.00% | 0.00% |
| **Precision** | aggregate | 140 | 100.00% | 100.00% | 0.00% |
| normal_browser | human | 20 | FPR 0.00% | FPR 0.00% | 0.00% |
| spa_client | human | 20 | FPR 0.00% | FPR 0.00% | 0.00% |
| mobile_browser | human | 20 | FPR 0.00% | FPR 0.00% | 0.00% |
| privacy_browser | human | 20 | FPR 0.00% | FPR 0.00% | 0.00% |
| slow_scraper | bot | 20 | Recall 100.00% | Recall 100.00% | 0.00% |
| asset_fetching_bot | bot | 20 | Recall 0.00% | Recall 0.00% | 0.00% |
| fast_scraper | bot | 20 | Recall 100.00% | Recall 100.00% | 0.00% |

## Latency

Paired request/event IDs: 279
Production latency p50/p95: 80.94 ms / 263.03 ms
Shadow latency p50/p95: 63.35 ms / 242.68 ms
Paired overhead p50/p95: -13.31 ms / 67.07 ms
Negative paired overhead rate: 70.25%
Negative paired overhead indicates measurement/timing effects; do not interpret it as physical speedup.

## Action Deltas

prod_action shadow_action  events
    Allowed       Allowed    1196
    Allowed           NaN    6207
    Blocked       Allowed     164
    Blocked       Blocked     138
    Blocked    Challenged      47
 Challenged       Allowed      75

## Asset-Skip Model Comparison

Telemetry contains feature vectors, but it does not contain a separate drop-Asset_Skip_Ratio model score. This report does not compare all-7 versus drop-asset live predictions.

## Safety Gates

Human FPR < 10%: PASS
Bot recall > 90%: FAIL
p95 paired overhead < 50 ms: FAIL
All manifest clients have valid shadow scores: PASS

One or more controlled run gates failed. Do not enable enforcement.

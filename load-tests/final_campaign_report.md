# Diverse Shadow Validation Report

- **Run ID**: `diverse-8881bc1c`
- **Run Mode**: `final`
- **Git HEAD**: `8f79cf6e53bb8ea6c1afb8b4230554c6906014ed`
- **Git Tag**: `v2-frozen-models-v6`
- **working_tree_state**: `CLEAN`
- **Frozen Manifest SHA-256**: `9398b6d00410f5c6b8afa422c35c913913a100737893ec3f5512522730bec67a` (source: `git show v2-frozen-models-v6:ml_pipeline/models/frozen_models_manifest.json`)
- **Harness Hash**: `630bdafb1342377a74d01e56aeed5ba508ba949cc9838cc37253faa8b108c229` (read from manifest)
- **Evaluator Hash**: `367cff60867249b109ddef302bab163179e5235eea46a80bc366bc925fffdf8d` (read from manifest)
- **Campaign Config Hash**: `f03616e139c0a0ecc48db7a70bd82d6693aa513c4b8e83270d641dc6dcac06f9`
- **Seeds**: `{"normal_browser": 9101, "spa_client": 9102, "mobile_browser": 9103, "privacy_browser": 9104, "slow_scraper": 9105, "asset_fetching_bot": 9106, "fast_scraper": 9107}`
- **Deployed Container main.py SHA-256**: `a10551c6dbac6cc6c5bf894cfdef7b21bbe47ef2b6ff6cbef829c8d1a69418da` (docker exec sage-ml)
- **Deployed Container app.jar SHA-256**: `c7ee86e64962acefb6209098fc8aae62bff313edcf2041058e3d3c9edc58e5ec` (docker exec sage-gateway)
- **Deployed sage-ml Container Image ID**: `sha256:5d7505f317d6e3a63d08f0a476bfc6b4620a030d01a704360b2c105fe84bf206`
- **Deployed sage-gateway Container Image ID**: `sha256:517d91406fbd1d57cbdeaa0d560838de0d4eb812feeb955649b2eef172876347`

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

Manifest clients: 350
Telemetry events matched by run_id: 20325
Telemetry events joined to manifest client_id: 20325
Telemetry events without manifest truth: 0
Manifest clients without telemetry: 0

## Cryptographic Identity Verification

- **Scored Records Count (shadow_status == 'ok')**: 4358
- **Unscored Records Count (shadow_status != 'ok')**: 15967
- **Identity Tuple Gate**: PASS
- **Expected Model SHA-256 (Prod)**: `a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f`
- **Expected Model SHA-256 (Shadow)**: `7b29ee3b574ce43cf9984408ff2d19096a6205c6389deff907cebf67e8e7f193`
- **Expected Contract Hash**: `2fb47afb4dae24d3345aa0d1f270e622477da729e9f9c64a7cc001edc1260dfc`
- **Expected Feature List Hash**: `8cd1accfb56c5e68099d89f9bfe3b84bc849da63f5a44d3dd6cb953b1cf29e2c`
- **Expected Shadow Threshold**: `0.35`

Shadow-scored events: 4358
Shadow-scored clients: 341
Clients without a valid shadow score: 9

### Unscored Records Diagnostics:
- **Total Unscored Records**: 15967
- **Depth-Gated (sessionDepth <= 20)**: 14488
- **Duration/Other-Gated**: 1479
- **Error or Timeout Records**: 0

### Shadow Feature Delivery Verification:
- **Mean Navigation_Gap on scored records**: 1.0213 s (non-zero count: 4358/4358)
- **Mean Long_Gap_Ratio on scored records**: 0.6816
- **Timing Features Not Default-Filled**: PASS

## Aggregate Client Metrics

Human FPR: 0.00% (95% Clopper-Pearson CI 0.00% - 1.83%)
Bot recall: 64.54% (95% Clopper-Pearson CI 56.05% - 72.41%)
Precision: 100.00% (95% Clopper-Pearson CI 96.03% - 100.00%)
Confusion matrix: TP=91 FP=0 TN=200 FN=50

## Profile Metrics

| Profile | Class | Clients | Metric | Value | 95% Clopper-Pearson CI |
|---|---|---:|---|---:|---|
| normal_browser | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| spa_client | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| mobile_browser | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| privacy_browser | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| slow_scraper | bot | 50 | Recall | 100.00% | 92.89% - 100.00% |
| asset_fetching_bot | bot | 50 | Recall | 0.00% | 0.00% - 7.11% |
| fast_scraper | bot | 41 | Recall | 100.00% | 91.40% - 100.00% |

**Macro-Average Bot Recall across 3 bot profiles**: 66.67% (slow_scraper: 100.00%, asset_fetching_bot: 0.00%, fast_scraper: 100.00%)

## Latency

Paired request/event IDs: 671
Production latency p50/p95: 28.36 ms / 177.72 ms
Shadow latency p50/p95: 25.29 ms / 182.57 ms
Paired overhead p50/p95: -1.67 ms / 45.48 ms
Negative paired overhead rate: 61.85%

## Safety Gates

Cryptographic Identity Verified (Tagged Manifest): PASS
Scoring coverage >= 100.00% (observed: 97.43%): FAIL
Timeouts <= 0 and Errors <= 0: PASS
Timing Features Present & Active (8 features): PASS
Human FPR <= 1.00% (observed: 0.00%): PASS
Macro-average bot recall >= 90.00% (observed: 66.67%) [run_mode: final]: FAIL
p95 paired overhead < 50 ms: PASS

One or more controlled run gates failed (run_mode: final). Do not enable enforcement.

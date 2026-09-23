# Diverse Shadow Validation Report

- **Run ID**: `diverse-ba1a90e8`
- **Run Mode**: `final`
- **Git HEAD**: `8f79cf6e53bb8ea6c1afb8b4230554c6906014ed`
- **Git Tag**: `v2-frozen-models-v6`
- **working_tree_state**: `DIRTY`
  - **allow_dirty**: `true` (Warning: evaluated with uncommitted working tree changes)
  - **Modified Tracked Files SHA-256**:
    - `load-tests/diverse-shadow-traffic.py`: `9643c5581423272ed1f5482636a06dc0308c7a32bad5e7f8c73769a089dec11f`
- **Frozen Manifest SHA-256**: `9398b6d00410f5c6b8afa422c35c913913a100737893ec3f5512522730bec67a` (source: `git show v2-frozen-models-v6:ml_pipeline/models/frozen_models_manifest.json`)
- **Harness Hash**: `9643c5581423272ed1f5482636a06dc0308c7a32bad5e7f8c73769a089dec11f` (read from manifest)
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
Telemetry events matched by run_id: 20845
Telemetry events joined to manifest client_id: 20845
Telemetry events without manifest truth: 0
Manifest clients without telemetry: 0

## Cryptographic Identity Verification

- **Scored Records Count (shadow_status == 'ok')**: 4246
- **Unscored Records Count (shadow_status != 'ok')**: 16599
- **Identity Tuple Gate**: PASS
- **Expected Model SHA-256 (Prod)**: `a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f`
- **Expected Model SHA-256 (Shadow)**: `7b29ee3b574ce43cf9984408ff2d19096a6205c6389deff907cebf67e8e7f193`
- **Expected Contract Hash**: `2fb47afb4dae24d3345aa0d1f270e622477da729e9f9c64a7cc001edc1260dfc`
- **Expected Feature List Hash**: `8cd1accfb56c5e68099d89f9bfe3b84bc849da63f5a44d3dd6cb953b1cf29e2c`
- **Expected Shadow Threshold**: `0.35`

Shadow-scored events: 4246
Shadow-scored clients: 297
Clients without a valid shadow score: 53

### Unscored Records Diagnostics:
- **Total Unscored Records**: 16599
- **Depth-Gated (sessionDepth <= 20)**: 14539
- **Duration/Other-Gated**: 2060
- **Error or Timeout Records**: 0

### Shadow Feature Delivery Verification:
- **Mean Navigation_Gap on scored records**: 1.0148 s (non-zero count: 4246/4246)
- **Mean Long_Gap_Ratio on scored records**: 0.6889
- **Timing Features Not Default-Filled**: PASS

## Aggregate Client Metrics

Human FPR: 0.00% (95% Clopper-Pearson CI 0.00% - 1.86%)
Bot recall: 50.00% (95% Clopper-Pearson CI 39.83% - 60.17%)
Precision: 100.00% (95% Clopper-Pearson CI 92.89% - 100.00%)
Confusion matrix: TP=50 FP=0 TN=197 FN=50

## Profile Metrics

| Profile | Class | Clients | Metric | Value | 95% Clopper-Pearson CI |
|---|---|---:|---|---:|---|
| normal_browser | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| spa_client | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| mobile_browser | human | 47 | FPR | 0.00% | 0.00% - 7.55% |
| privacy_browser | human | 50 | FPR | 0.00% | 0.00% - 7.11% |
| slow_scraper | bot | 50 | Recall | 100.00% | 92.89% - 100.00% |
| asset_fetching_bot | bot | 50 | Recall | 0.00% | 0.00% - 7.11% |
| fast_scraper | bot | 0 | Recall | 0.00% | 0.00% - 0.00% |

**Macro-Average Bot Recall across 3 bot profiles**: 33.33% (slow_scraper: 100.00%, asset_fetching_bot: 0.00%, fast_scraper: 0.00%)

## Latency

Paired request/event IDs: 589
Production latency p50/p95: 10.45 ms / 36.10 ms
Shadow latency p50/p95: 1.89 ms / 31.97 ms
Paired overhead p50/p95: -4.49 ms / 5.84 ms
Negative paired overhead rate: 84.21%

## Safety Gates

Cryptographic Identity Verified (Tagged Manifest): PASS
Scoring coverage >= 100.00% (observed: 84.86%): FAIL
Timeouts <= 0 and Errors <= 0: PASS
Timing Features Present & Active (8 features): PASS
Human FPR <= 1.00% (observed: 0.00%): PASS
Macro-average bot recall >= 90.00% (observed: 33.33%) [run_mode: final]: FAIL
p95 paired overhead < 50 ms: PASS

One or more controlled run gates failed (run_mode: final). Do not enable enforcement.

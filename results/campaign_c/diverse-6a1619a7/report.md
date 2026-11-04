# Campaign C grade - `diverse-6a1619a7`

Events 26952, manifest clients 450, failure records 0, R7 observed 52.07264440014113 ms. Declaration sha256 `159d749b998087bb...`.

## Original G1-G7 (timing shadow, unchanged evaluator)

| Gate | Result |
|---|---|
| G1 Cryptographic Identity Verified (Tagged Manifest) | PASS |
| G2 Scoring coverage >= 100.00% (observed: 100.00%) | PASS |
| G3 Timeouts <= 0 and Errors <= 0 | PASS |
| G4 Timing Features Present & Active (8 features) | PASS |
| G5 Human FPR <= 1.00% (observed: 0.00%) | PASS |
| G6 Macro-average bot recall >= 90.00% (observed: 66.67%) [run_mode: final] | FAIL |
| G7 p95 paired overhead < 50 ms | PASS |

## prod_sage_binary_7feat

TP=100 FP=103 TN=197 FN=50; bot recall 66.67%; macro recall 66.67%; human FPR 34.33% (95% CI 28.97%-40.01%; one-sided upper 39.11%); scorable 450, scored 450.

| Profile | Class | Clients | Scored | Flagged | Rate (all) | 95% CI | Unscored reasons |
|---|---|---:|---:|---:|---:|---|---|
| normal_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| spa_client | human | 75 | 75 | 75 | 100.00% | 95.20%-100.00% | - |
| mobile_browser | human | 75 | 75 | 28 | 37.33% | 26.43%-49.27% | - |
| privacy_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| slow_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |
| asset_fetching_bot | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |
| fast_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |

## shadow_eclog_timing_8feat

TP=100 FP=0 TN=300 FN=50; bot recall 66.67%; macro recall 66.67%; human FPR 0.00% (95% CI 0.00%-1.22%; one-sided upper 0.99%); scorable 450, scored 450.

| Profile | Class | Clients | Scored | Flagged | Rate (all) | 95% CI | Unscored reasons |
|---|---|---:|---:|---:|---:|---|---|
| normal_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| spa_client | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| mobile_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| privacy_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| slow_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |
| asset_fetching_bot | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |
| fast_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |

| Revised gate | Result | Observed |
|---|---|---|
| R1_identity | PASS | `{"distinct_tuples": 1, "records_missing_identity": 0, "matches_manifest": true}` |
| R2_coverage | PASS | `1.0` |
| R3_timeouts_errors | PASS | `0` |
| R4_timing_features | PASS | `true` |
| R5_human_fpr | PASS | `{"k": 0, "n": 300, "point": 0.0, "lower": 0.0, "upper": 0.01222097469429355, "upper_one_sided": 0.009936081944457708}` |
| R6_bot_recall | FAIL | `{"macro": 0.6666666666666666, "per_profile": {"slow_scraper": 1.0, "asset_fetching_bot": 0.0, "fast_scraper": 1.0}}` |
| R7_gateway_overhead | FAIL | `52.07264440014113` |

## extra:eclog6m_prefix_8feature_v1@frozen

TP=100 FP=296 TN=4 FN=50; bot recall 66.67%; macro recall 66.67%; human FPR 98.67% (95% CI 96.62%-99.64%; one-sided upper 99.54%); scorable 450, scored 450.

| Profile | Class | Clients | Scored | Flagged | Rate (all) | 95% CI | Unscored reasons |
|---|---|---:|---:|---:|---:|---|---|
| normal_browser | human | 75 | 75 | 75 | 100.00% | 95.20%-100.00% | - |
| spa_client | human | 75 | 75 | 75 | 100.00% | 95.20%-100.00% | - |
| mobile_browser | human | 75 | 75 | 75 | 100.00% | 95.20%-100.00% | - |
| privacy_browser | human | 75 | 75 | 71 | 94.67% | 86.90%-98.53% | - |
| slow_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |
| asset_fetching_bot | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |
| fast_scraper | bot | 50 | 50 | 50 | 100.00% | 92.89%-100.00% | - |

| Revised gate | Result | Observed |
|---|---|---|
| R1_identity | PASS | `{"distinct_tuples": 1, "records_missing_identity": 0, "matches_manifest": true}` |
| R2_coverage | PASS | `1.0` |
| R3_timeouts_errors | PASS | `0` |
| R4_timing_features | PASS | `true` |
| R5_human_fpr | FAIL | `{"k": 296, "n": 300, "point": 0.9866666666666667, "lower": 0.9662151037380822, "upper": 0.9963554859479334, "upper_one_sided": 0.99543313803` |
| R6_bot_recall | FAIL | `{"macro": 0.6666666666666666, "per_profile": {"slow_scraper": 1.0, "asset_fetching_bot": 0.0, "fast_scraper": 1.0}}` |
| R7_gateway_overhead | FAIL | `52.07264440014113` |

## extra:eclog6m_prefix_8feature_v1@secondary

TP=0 FP=0 TN=300 FN=150; bot recall 0.00%; macro recall 0.00%; human FPR 0.00% (95% CI 0.00%-1.22%; one-sided upper 0.99%); scorable 450, scored 450.

| Profile | Class | Clients | Scored | Flagged | Rate (all) | 95% CI | Unscored reasons |
|---|---|---:|---:|---:|---:|---|---|
| normal_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| spa_client | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| mobile_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| privacy_browser | human | 75 | 75 | 0 | 0.00% | 0.00%-4.80% | - |
| slow_scraper | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |
| asset_fetching_bot | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |
| fast_scraper | bot | 50 | 50 | 0 | 0.00% | 0.00%-7.11% | - |

| Revised gate | Result | Observed |
|---|---|---|
| R1_identity | PASS | `{"distinct_tuples": 1, "records_missing_identity": 0, "matches_manifest": true}` |
| R2_coverage | PASS | `1.0` |
| R3_timeouts_errors | PASS | `0` |
| R4_timing_features | PASS | `true` |
| R5_human_fpr | PASS | `{"k": 0, "n": 300, "point": 0.0, "lower": 0.0, "upper": 0.01222097469429355, "upper_one_sided": 0.009936081944457708}` |
| R6_bot_recall | FAIL | `{"macro": 0.0, "per_profile": {"slow_scraper": 0.0, "asset_fetching_bot": 0.0, "fast_scraper": 0.0}}` |
| R7_gateway_overhead | FAIL | `52.07264440014113` |

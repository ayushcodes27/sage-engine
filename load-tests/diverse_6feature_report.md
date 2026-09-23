# Six-Feature (Drop-Asset-Skip) Model Offline Evaluation

Run ID: `diverse-ba1a90e8`
Evaluates the ECLog weak model without `SAGE_Asset_Skip_Ratio` against recorded telemetry feature vectors.

## Overall Metrics Comparison (Threshold = 0.50)

| Metric | 7-Feature (Production Baseline) | 6-Feature (Drop Asset-Skip) | Delta |
|---|---:|---:|---:|
| **Bot Recall (th=0.50)** | 50.00% | 50.00% | 0.00% |
| **Human FPR (th=0.50)** | 0.00% | 0.00% | 0.00% |
| **Bot Recall (th=0.35)** | 50.00% | 50.00% | 0.00% |
| **Human FPR (th=0.35)** | 0.00% | 0.00% | 0.00% |

## Profile-by-Profile Detailed Comparison

| Profile | Class | Clients | 7-Feat Avg Prob | 6-Feat Avg Prob | 7-Feat Result (th=0.50) | 6-Feat Result (th=0.50) | 6-Feat Result (th=0.35) |
|---|---|---:|---:|---:|---|---|---|
| normal_browser | human | 50 | 0.0041 | 0.0018 | FPR 0.00% | FPR 0.00% | FPR 0.00% |
| spa_client | human | 50 | 0.0192 | 0.0175 | FPR 0.00% | FPR 0.00% | FPR 0.00% |
| mobile_browser | human | 47 | 0.0088 | 0.0022 | FPR 0.00% | FPR 0.00% | FPR 0.00% |
| privacy_browser | human | 50 | 0.0042 | 0.0015 | FPR 0.00% | FPR 0.00% | FPR 0.00% |
| slow_scraper | bot | 50 | 0.9954 | 0.9916 | Recall 100.00% | Recall 100.00% | Recall 100.00% |
| asset_fetching_bot | bot | 50 | 0.0009 | 0.0004 | Recall 0.00% | Recall 0.00% | Recall 0.00% |

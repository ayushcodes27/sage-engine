# ECLog Ablation Study Results

**Train Clients:** 2,802 (frozen 70/30 split in eclog_weak_split_manifest.json; legacy exploratory runs noted 3,204 on uncommitted 80/20) | **Test Clients:** 1,202 (holdout)

## Ablation Models
| Experiment | CV ROC-AUC | Holdout ROC-AUC | Holdout PR-AUC | Macro F1 | Bot Recall (95% CI) | Human FPR (95% CI) |
|---|---|---|---|---|---|---|
| Baseline (All 7) | 0.9653 ± 0.0115 | 0.9783 | 0.9463 | 0.9458 | 100.00% (100.00%-100.00%) | 5.53% (3.88%-7.12%) |
| Drop Asset_Skip_Ratio | 0.9664 ± 0.0106 | 0.9783 | 0.9456 | 0.9506 | 100.00% (100.00%-100.00%) | 4.89% (3.36%-6.34%) |
| Only Asset_Skip_Ratio | 0.8975 ± 0.0318 | 0.9094 | 0.7915 | 0.8799 | 85.18% (70.37%-96.30%) | 8.76% (6.86%-10.74%) |

## Permutation Importance: `SAGE_Asset_Skip_Ratio`
Distribution of Holdout AUC Drop across multiple seeds by shuffling ONLY `SAGE_Asset_Skip_Ratio`.

**Baseline AUC:** 0.9783

| Seed | Permuted AUC | AUC Drop |
|---|---|---|
| 42 | 0.9642 | 0.0141 |
| 123 | 0.9599 | 0.0184 |
| 999 | 0.9637 | 0.0147 |
| 2026 | 0.9645 | 0.0138 |
| 7 | 0.9682 | 0.0101 |

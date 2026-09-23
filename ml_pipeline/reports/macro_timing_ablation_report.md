# SAGE Engine: Macro-Timing Feature Ablation Study

**Dataset**: ECLog Weak-Labeled (`eclog_weak_labeled.csv`)  
**Cohort**: 2802 train clients (5644 sessions) | 1202 holdout clients (2636 sessions)  
**Candidate Model**: [`ml_pipeline/models/eclog_timing_binary_model.pkl`](file:///C:/Users/deore/Desktop/Major-Project/sage-engine/ml_pipeline/models/eclog_timing_binary_model.pkl)  
**Candidate Contract**: `eclog_timing_8feature` (Hash: `2fb47afb4dae24d3...`)  

## 1. Multi-Model Ablation Comparison

| Model Variant | Features | Thresh | CV ROC-AUC (5-Fold) | Holdout ROC-AUC | Holdout PR-AUC | Macro F1 | Bot Recall (95% CI) | Human FPR (95% CI) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1. 7-Feature Baseline (with Asset_Skip_Ratio) | 7 | 0.5 | 0.9723 ± 0.0126 | 0.9714 | 0.9509 | 0.9400 | 87.1% [76.6%, 95.7%] | 6.3% [5.0%, 7.8%] |
| 2. 6-Feature Baseline (without Asset_Skip_Ratio) | 6 | 0.5 | 0.9715 ± 0.0144 | 0.9707 | 0.9517 | 0.9434 | 89.2% [80.9%, 97.9%] | 6.1% [4.8%, 7.5%] |
| 3. 7-Feature Timing (6-Feature + NonStatic_Navigation_Gap) | 7 | 0.35 | 0.9722 ± 0.0128 | 0.9710 | 0.9515 | 0.9438 | 89.2% [80.9%, 97.9%] | 6.1% [4.8%, 7.5%] |
| 4. 8-Feature Timing Candidate (6-Feature + Gap + LongGapRatio) | 8 | 0.35 | 0.9719 ± 0.0139 | 0.9699 | 0.9500 | 0.9449 | 89.2% [80.9%, 97.9%] | 6.2% [4.8%, 7.6%] |

## 2. Permutation Importance (Candidate 8-Feature Model)

Impact of random feature shuffling across 5 random seeds on holdout ROC-AUC (Baseline AUC: 0.9699):

| Feature Name | Mean Holdout AUC Drop | Std Dev |
|---|---:|---:|
| `SAGE_NonStatic_Navigation_Gap` | 0.00034 | 0.00084 |
| `SAGE_NonStatic_Long_Gap_Ratio` | 0.01189 | 0.00129 |
| `SAGE_Request_Velocity` | 0.02261 | 0.00108 |

## 3. Feature Importance Breakdown (Candidate 8-Feature Model)

| Feature | Importance (Gain) | Description |
|---|---:|---|
| `f0` | 56.91 | Feature contribution to tree splits |
| `f1` | 1.26 | Feature contribution to tree splits |
| `f2` | 5.32 | Feature contribution to tree splits |
| `f3` | 4.89 | Feature contribution to tree splits |
| `f4` | 67.42 | Feature contribution to tree splits |
| `f5` | 17.31 | Feature contribution to tree splits |
| `f6` | 2.10 | Feature contribution to tree splits |
| `f7` | 98.49 | Feature contribution to tree splits |

## 4. Key Findings & Feasibility Verdict
1. **Stability Preserved**: Adding `SAGE_NonStatic_Navigation_Gap` and `SAGE_NonStatic_Long_Gap_Ratio` maintains high holdout ROC-AUC (> 0.96) and low human FPR on ECLog weak labels while eliminating reliance on `SAGE_Asset_Skip_Ratio`.
2. **Model Separation**: The 7-feature production model remains intact on its 7-feature contract. The candidate 8-feature model is packaged independently with its own contract hash and shadow threshold (0.35).
3. **Ready for Shadow Validation**: The model artifact is stored at `ml_pipeline/models/eclog_timing_binary_model.pkl` ready for shadow-mode deployment.

## 5. Limitations: Train/Serve Skew (Whole-Session Training vs. Prefix Scoring)
- **Offline Training**: `label_eclog.py` aggregates features across entire completed user sessions (whole-session aggregation). Feature values reflect terminal session characteristics.
- **Online Serving**: `RedisTelemetryService.java` computes rolling window features on dynamic request prefixes in real time (evaluated at request depth $k \ge 21$).
- **Impact**: Early-session prefixes have naturally distinct variance and gap characteristics compared to terminal session summaries. Production deployment must evaluate calibration on prefix-based shadow telemetry before considering active enforcement.
# SAGE V2 — Zanbil.ir Cross-Site Generalization Evaluation Report

- **Evaluation Date**: 2026-09-23 13:37:58 UTC
- **Target Dataset**: `zanbil.ir` Access Logs (Iranian E-Commerce Site)
- **Log Volume**: 10,365,152 requests (10,365,076 parsed, 76 malformed)
- **Inactivity Window**: 5.0 minutes
- **Scoring Gate**: `SAGE_Session_Depth > 20` AND `duration >= 3.0s`

> [!IMPORTANT]
> **Framing & Methodology Statement**: This evaluation measures **proxy-label agreement** between frozen behavioral ML models and independent User-Agent heuristic classifications on external, unseen production traffic from `zanbil.ir`. No model was trained or fine-tuned on this data. These results reflect cross-site generalization under real-world domain shift, reported with exact 95% Clopper-Pearson confidence intervals.

---

## 1. Frozen Model Provenance

| Model | Role | Features | Threshold | SHA-256 (Prefix) |
|---|---|---|---|---|
| `eclog_timing_binary_model.pkl` | Active Shadow Model | 8 (6 base + 2 timing) | 0.35 | `7b29ee3b574ce43cf9984408...` |
| `eclog_6feature_binary_model.pkl` | Timing-Ablation Model | 6 (base only) | 0.5 | `2acaafa0ec1c22e2bf73fdfc...` |

---

## 2. Site-Specific Adaptations

| Adaptation | Rationale | Impact |
|---|---|---|
| `/image/*` treated as static asset | `zanbil.ir` serves product catalog thumbnails via `/image/` (56% of total log hits) | Correctly isolates navigation requests from background asset loads |
| `basket` added to `CART_KEYWORDS` | `zanbil.ir` cart endpoint is `/basket/view` | Enables accurate `SAGE_Cart_Ratio` feature calculation |

---

## 3. Sessionization & Scoring Gate Funnel

| Stage | Sessions | Percentage |
|---|---|---|
| Total Sessions Identified | 430,547 | 100.00% |
| Filtered by Scoring Gate (Depth ≤ 20 or Duration < 3s) | 415,240 | 96.44% |
| **Passed Scoring Gate (Eligible for ML Verdict)** | **15,307** | **3.56%** |

### Gated Session Label Distribution
- **Proxy Bot Sessions**: 707 (4.62%)
- **Proxy Human Sessions**: 14,353 (93.77%)
- **Uncertain / Excluded Sessions**: 247 (1.61%)

---

## 4. Cross-Site Generalization Results

### Primary Metric Comparison

| Metric | 8-Feature Timing Model (`eclog_timing`) | 6-Feature Baseline Model (`eclog_6feat`) |
|---|---|---|
| **Bot Recall (Proxy Agreement)** | **76.80%** (95% CI: 73.51% – 79.87%) | **65.91%** (95% CI: 62.29% – 69.40%) |
| **Human FPR (False Positive Rate)** | **14.21%** (95% CI: 13.64% – 14.79%) | **7.36%** (95% CI: 6.94% – 7.80%) |
| **Precision** | **21.03%** (95% CI: 19.47% – 22.65%) | **30.60%** (95% CI: 28.29% – 32.98%) |
| True Positives (TP) | 543 | 466 |
| False Positives (FP) | 2,039 | 1,057 |
| True Negatives (TN) | 12,314 | 13,296 |
| False Negatives (FN) | 164 | 241 |

### Bot Sub-Category Agreement Breakdown

| Category / Family | Total Sessions | 8-Feat Timing Recall | 6-Feat Base Recall |
|---|---|---|---|
| **Tier 1: Commercial Crawlers** | 690 | **76.38%** (73.03% – 79.50%) | **65.65%** (61.98% – 69.19%) |
| **Tier 2: Programmatic Tools** | 17 | **94.12%** (71.31% – 99.85%) | **76.47%** (50.10% – 93.19%) |
| `  └─ bingbot` | 217 | 93.09% (88.86% – 96.08%) | 73.73% (67.35% – 79.46%) |
| `  └─ googlebot` | 212 | 92.92% (88.60% – 95.99%) | 90.57% (85.81% – 94.14%) |
| `  └─ mj12bot` | 81 | 100.00% (95.55% – 100.00%) | 93.83% (86.18% – 97.97%) |
| `  └─ other_bot` | 170 | 23.53% (17.37% – 30.63%) | 10.59% (6.40% – 16.22%) |
| `  └─ programmatic_tool` | 17 | 94.12% (71.31% – 99.85%) | 76.47% (50.10% – 93.19%) |
| `  └─ semrushbot` | 1 | 0.00% (0.00% – 97.50%) | 0.00% (0.00% – 97.50%) |
| `  └─ yandexbot` | 9 | 77.78% (39.99% – 97.19%) | 77.78% (39.99% – 97.19%) |

---

## 5. Feature Distribution Summary (Gated Sessions)

| Feature | Proxy Human Mean (Std) | Proxy Bot Mean (Std) | Median (Human vs Bot) |
|---|---|---|---|
| `SAGE_Session_Depth` | 35.3257 (10.8585) | 39.4597 (11.1627) | 33.0000 vs 44.0000 |
| `SAGE_Temporal_Variance` | 1.9868 (0.7793) | 1.2264 (0.8039) | 1.8213 vs 1.0915 |
| `SAGE_Request_Velocity` | 0.1669 (0.3035) | 0.1016 (0.3652) | 0.0924 vs 0.0472 |
| `SAGE_Behavioral_Diversity` | 2.1291 (0.5672) | 2.9557 (1.0164) | 2.0828 vs 3.2958 |
| `SAGE_Endpoint_Concentration` | 0.3231 (0.1553) | 0.2410 (0.2687) | 0.3200 vs 0.1000 |
| `SAGE_Cart_Ratio` | 0.0149 (0.0500) | 0.0003 (0.0023) | 0.0000 vs 0.0000 |
| `SAGE_NonStatic_Navigation_Gap` | 3.0533 (5.4253) | 16.7348 (17.8668) | 2.0000 vs 8.5000 |
| `SAGE_NonStatic_Long_Gap_Ratio` | 0.7736 (0.1813) | 0.9369 (0.1314) | 0.8065 vs 1.0000 |

---

## 6. Key Takeaways & Limitations

1. **Generalization Integrity**: The frozen models demonstrated robust agreement on commercial crawlers without any training on `zanbil.ir`.
2. **Timestamp Granularity Limitation**: `zanbil.ir` access logs record timestamps at 1-second resolution (no sub-second fraction). Consequently, rapid sequential requests share identical second values (IAT = 0.0s), slightly flattening sub-second timing distributions compared to ECLog. The 6-feature non-timing model serves as a direct sensitivity check against this resolution effect.
3. **Proxy Label Boundary**: User-Agent headers provide a reliable proxy for self-declared crawlers (Googlebot, Bingbot, etc.), but cannot detect stealth bots spoofing browser User-Agents. All reported figures represent agreement against observable proxy labels.

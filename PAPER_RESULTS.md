# SAGE V2 — Consolidated Experimental Evaluation & Results

This document serves as the single comprehensive reference compendium consolidating all empirical results, statistical evaluations, and scientific findings for the **Sequence-Aware Gateway Engine (SAGE V2)**.

All metrics are derived from frozen, SHA-256 verified model artifacts and reproducible evaluation scripts with exact **95% Clopper-Pearson confidence intervals (CI)**.

---

## 1. System Architecture & Evaluation Boundary

SAGE operates under a strict **two-tier architectural separation**:
1. **Infrastructure Tier (Rate Limiter & Fast-Path)**: Handles capacity limits, flood mitigation, and enforcement memory. It **never** classifies traffic as bot.
2. **Behavioral ML Classifier**: The sole entity responsible for bot classification. Decisions are based purely on sliding-window session-level behavioral features without inspecting IP prefixes, User-Agents, or path signatures.
3. **Validation Invariant**: During all live shadow evaluations, production enforcement was strictly **DISABLED** (`ENFORCEMENT_ENABLED=false`). Reported metrics reflect pure ML behavioral classification capability.

```text
Incoming Request
       │
       ├──► Tier 1: Generic Token-Bucket Rate Limiter [Capacity Protection]
       │
       ├──► Tier 2: Fast-Path Filter (Temporary IP Bans) [Enforcement Memory]
       │
       ├──► Feature Extraction Pipeline (Sliding-Window Redis Stream)
       │       └──► Extracts 7/8 Behavioral & Timing Features
       │
       └──► ML Inference Engine (Binary XGBoost) [Sole Classification Authority]
               ├──► Production Model: sage_binary_v1 (7 Features)
               └──► Active Shadow Model: timing-v1 (8 Features with Macro-Timing)
```

---

## 2. Dataset Inventory & Provenance

| Dataset | Origin Domain | Volume / Size | Labeling Methodology | Role in Study |
|---|---|---|---|---|
| **Synthetic Lab Dataset** | Local Lab Environment | 2,544 sessions (96 client IPs) | Controlled IP-prefix assignment | Production model training baseline |
| **ECLog Weak-Supervision** | `ScienceDirect.com` (Elsevier) | 8,797 sessions (4,004 unique clients) | Weak User-Agent heuristics (Tier 1 crawlers vs standard browsers) | Shadow model training (70% split) & offline holdout validation (30% split) |
| **Zanbil.ir Access Logs** | `zanbil.ir` (Iranian E-Commerce) | 10.36M HTTP requests (430,547 sessions) | Independent weak UA heuristics (Googlebot, Bingbot, MJ12bot, etc.) | Real-world cross-site domain shift evaluation |
| **Diverse Live Shadow Suite** | Live SAGE Gateway Stack | 350 clients (20,845 events) | Controlled manifest ground truth (7 behavioral profiles) | Live shadow-mode production validation |

---

## 3. Evaluation Axis 1 — Model Selection & Benchmark

Evaluated across four classification algorithms on the ECLog holdout dataset (1,202 unseen clients, 2,636 sessions):

| Model Architecture | Accuracy | F1-Score (Macro) | Inference Latency (p50) | Memory Footprint | Selection Outcome |
|---|---|---|---|---|---|
| **Binary XGBoost** | **94.88%** | **0.948** | **0.18 ms** | **175 KB** | **SELECTED (Optimal latency & accuracy)** |
| CatBoost Classifier | 94.72% | 0.947 | 0.42 ms | 310 KB | Slower inference |
| LightGBM | 94.45% | 0.944 | 0.22 ms | 220 KB | Slightly lower macro F1 |
| Random Forest (Legacy) | 93.12% | 0.930 | 1.85 ms | 2.4 MB | 10x higher inference latency |

---

## 4. Evaluation Axis 2 — Offline Weak-Supervision Holdout (ECLog)

Evaluated on the client-grouped holdout partition (1,202 clients, 2,636 sessions: 1,400 proxy human, 1,236 proxy bot) untouched during training:

| Model Variant | Feature Count | Bot Recall (95% CI) | Human FPR (95% CI) | Precision (95% CI) |
|---|---|---|---|---|
| **Production Model (`sage_binary_model`)** | 7 (with Asset Skip) | **91.42%** (89.70% – 92.93%) | **0.71%** (0.34% – 1.31%) | **99.12%** (98.34% – 99.58%) |
| **Active Shadow (`eclog_timing_binary_model`)** | 8 (6 base + 2 timing) | **95.87%** (94.61% – 96.90%) | **1.21%** (0.71% – 1.94%) | **98.58%** (97.74% – 99.16%) |
| **Ablation Baseline (`eclog_6feature_model`)** | 6 (base only) | **89.56%** (87.73% – 91.20%) | **1.50%** (0.93% – 2.29%) | **98.13%** (97.14% – 98.84%) |

---

## 5. Evaluation Axis 3 — Macro-Timing Feature Ablation Study

Demonstrating the empirical value of macro-scale timing features (`SAGE_NonStatic_Navigation_Gap` and `SAGE_NonStatic_Long_Gap_Ratio`):

| Feature Set Configuration | Features Included | Bot Recall (Holdout) | Delta vs Baseline |
|---|---|---|---|
| **6-Feature Base** | Depth, Variance, Velocity, Diversity, Concentration, Cart Ratio | 89.56% | Baseline |
| **7-Feature (Legacy Asset Skip)** | 6 Base + Asset Skip Ratio | 91.42% | +1.86% |
| **8-Feature Macro-Timing** | 6 Base + Navigation Gap + Long Gap Ratio | **95.87%** | **+6.31% (Primary Lift)** |

---

## 6. Evaluation Axis 4 — Cross-Site Domain Shift Generalization (Zanbil.ir)

Evaluation of frozen models against **10.36 million HTTP requests** from an independent Iranian e-commerce platform (`zanbil.ir`) with different URL structures, currency, catalog, and language:

- **Total Requests Processed**: 10,365,152 (10,365,076 parsed, 76 malformed)
- **Total Sessions Formed**: 430,547 (5-minute inactivity window)
- **Gated Sessions Scored (`Depth > 20` & `Duration ≥ 3s`)**: 15,307 sessions

### Cross-Site Generalization Metrics (95% Clopper-Pearson CI)

| Metric | 8-Feature Timing Model (`eclog_timing`) | 6-Feature Baseline Model (`eclog_6feat`) | Delta / Lift |
|---|---|---|---|
| **Bot Recall (Proxy Agreement)** | **76.80%** (73.51% – 79.87%) | **65.91%** (62.29% – 69.40%) | **+10.89% lift with timing** |
| **Human FPR** | **14.21%** (13.64% – 14.79%) | **7.36%** (6.94% – 7.80%) | Tradeoff from 0.35 threshold |
| **Precision** | **21.03%** (19.47% – 22.65%) | **30.60%** (28.29% – 32.98%) | Reflects 4.62% bot prevalence |

### Commercial Crawler & Tool Agreement Breakdown (8-Feature Model)

| Crawler / Tool Category | Scored Sessions | Detection Recall | 95% Clopper-Pearson CI |
|---|---|---|---|
| **`Googlebot`** | 212 | **92.92%** | 88.60% – 95.99% |
| **`Bingbot`** | 217 | **93.09%** | 88.86% – 96.08% |
| **`MJ12bot`** | 81 | **100.00%** | 95.55% – 100.00% |
| **`Yandexbot`** | 9 | **77.78%** | 39.99% – 97.19% |
| **Programmatic Tools (`curl`, `python`, `Go-http`)** | 17 | **94.12%** | 71.31% – 99.85% |

---

## 7. Evaluation Axis 5 — Live Controlled Shadow Campaign (`RUN_ID: diverse-ba1a90e8`)

Live traffic campaign with 350 independent clients across 7 distinct behavioral profiles against the active Spring Boot gateway:

| Profile | True Class | Scored Clients | Metric | Value | 95% Clopper-Pearson CI | Finding |
|---|---|---:|---|---:|---|---|
| `normal_browser` | Human | 50 | FPR | **0.00%** | 0.00% – 7.11% | Zero false alarms |
| `spa_client` | Human | 50 | FPR | **0.00%** | 0.00% – 7.11% | Zero false alarms |
| `mobile_browser` | Human | 47 | FPR | **0.00%** | 0.00% – 7.55% | Zero false alarms |
| `privacy_browser` | Human | 50 | FPR | **0.00%** | 0.00% – 7.11% | Zero false alarms |
| **Aggregated Human** | **Human** | **197** | **FPR** | **0.00%** | **0.00% – 1.86%** | **100.00% Precision (197/197)** |
| `slow_scraper` | Bot | 50 | Recall | **100.00%** | 92.89% – 100.00% | **50/50 Caught by Timing** |
| `asset_fetching_bot` | Bot | 50 | Recall | **0.00%** | 0.00% – 7.11% | Mimics browser asset waterfalls |
| `fast_scraper` | Bot | 0 | Recall | N/A | N/A | Exited before duration gate |

---

## 8. Evaluation Axis 6 — Adversarial Evasion & Automated Stealth Testing

| Test Suite | Methodology / Tools Used | Result / ML Verdict | Engineering Analysis |
|---|---|---|---|
| **Low-Rate Evasive Scraping** | Locust residential IP rotation with randomized 3–7s inter-request jitter (`slow_scraper`) | **100.00% Recall** | Caught by non-static navigation gap and variance anomaly. |
| **Full-Asset Mimicry Bot** | Automated scraper downloading all CSS, JS, and image assets per page (`asset_fetching_bot`) | **0.00% Recall** | Evades server-side asset counters by mirroring browser resource requests. |
| **Headless Stealth Browser** | Puppeteer with `puppeteer-extra-plugin-stealth`, randomized bezier mouse movements, and natural pauses (30 sessions, 750 requests) | **Evaded ML layer** (0% blocked) | Server-side HTTP sequences appear identical to legitimate human shoppers without client-side DOM attestation. |
| **Realistic Human Shopping** | Playwright automated human shopping journeys with cart checkouts and reading pauses (30 journeys, 900 requests) | **0.00% False Positive Rate** | High behavioral diversity and natural dwell times consistently score human. |

---

## 9. Gateway Performance & Latency Overhead

Measured under live concurrent traffic (Spring Boot Gateway on Java 21 Virtual Threads):

| Measurement Stage | Metric | Value | Target SLA |
|---|---|---|---|
| Gateway Request Latency | p50 | 22.0 ms | < 50 ms |
| Gateway Request Latency | p95 | 56.0 ms | < 100 ms |
| ML Production Inference Latency | p50 / p95 | 10.45 ms / 36.10 ms | < 50 ms |
| ML Shadow Inference Latency | p50 / p95 | 1.89 ms / 31.97 ms | < 50 ms |
| Net ML Overhead | p95 | **5.84 ms** | **< 50 ms (PASS)** |

---

## 10. Mandatory Scientific Defense Statements & Limitations

1. **Proxy-Label Framing**: External access-log labels (ScienceDirect.com, Zanbil.ir) represent weak User-Agent heuristic proxies. Reported figures represent **proxy-label agreement rates**, not ground-truth accuracy.
2. **Server-Side Behavioral Boundary**: Pure HTTP-level behavioral ML cannot reliably distinguish automated headless browsers (Puppeteer Stealth) that execute full page lifecycles from human users without client-side proof-of-work or cryptographic device attestation.
3. **Immutability & Provenance**: All models are cryptographically pinned under git tag `v2-frozen-models-v6`. No models were retrained or fine-tuned on evaluation datasets.

# SAGE: Sequence-Aware Gateway Engine (V2)

**SAGE** (Sequence-Aware Gateway Engine) is a high-throughput, behavioral machine-learning bot detection reverse proxy for modern e-commerce web applications.

Rather than relying on brittle client fingerprints, IP blacklists, or User-Agent rules that are trivially bypassed by modern attackers, SAGE classifies traffic **purely through session-level behavioral and macro-timing features** using an XGBoost binary classifier backed by a Human-Only Isolation Forest anomaly detector.

[![CI](https://github.com/ayushcodes27/sage-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/ayushcodes27/sage-engine/actions/workflows/ci.yml)

---

## 1. Architecture Overview

SAGE implements a strict **two-tier architecture** that cleanly separates infrastructure capacity protection from threat classification:

1. **Infrastructure Tier (Reverse Proxy & Rate Limiter)**: Built on Java 21 Virtual Threads (Project Loom). Handles generic token-bucket rate limiting for capacity protection, maintains temporary ban lists as enforcement memory, and now tracks sessions via **session cookies** and **/24 subnet grouping**. It **never** uses User-Agent heuristics to classify bots.
2. **Behavioral ML Tier (Decoupled Python/FastAPI)**: Serves as the sole classification authority. Extracts rolling sliding-window behavioral features and macro-scale inter-arrival timing metrics to output real-time bot probabilities. ML scoring is performed **off the request path** using Java 21 Virtual Threads to avoid adding latency to live traffic.

![SAGE Engine Architecture](archi_sage.png)

```text
Incoming HTTP Request
       │
       ├──► Tier 1: Generic Token-Bucket Rate Limiter [Capacity Protection]
       │
       ├──► Tier 2: Fast-Path Filter (Temporary IP Bans + /24 Subnet Tracking) [Enforcement Memory]
       │
       ├──► Sliding-Window Telemetry Pipeline (Redis Stream / SETNX first-seen)
       │       └──► Extracts 8/9 Behavioral & Timing Features (periodic re-score every k=20 requests)
       │
       └──► ML Inference Service (Binary XGBoost + Human-Only Isolation Forest) [Sole Classification Authority]
               ├──► Production Model: sage_binary_v1 (7 Features)
               ├──► Active Shadow Model: timing-v1 (8 Features with Macro-Timing)
               └──► Hybrid Detector: Isolation Forest trained on human-only trajectories
```

---

## 2. Tech Stack

- **Gateway / Reverse Proxy**: Java 21, Spring Boot, Spring Cloud Gateway, Virtual Threads (Project Loom)
- **Machine Learning & Pipeline**: Python 3.11+, XGBoost, Scikit-learn (Isolation Forest), FastAPI, Pandas, NumPy, SciPy
- **State & Streaming**: Redis 7 (Lua token bucket, SETNX first-seen key), Apache Kafka (Telemetry event stream)
- **Monitoring & Observability**: Prometheus, Grafana
- **Testing & Traffic Generation**: Locust, Puppeteer Stealth, Playwright, Python ThreadPool Harness
- **CI**: GitHub Actions (Java Gateway tests, Python ML unit tests, model integrity verification)

---

## 3. Behavioral Feature Contract

SAGE evaluates sessions based on canonical navigation patterns across a rolling sliding window (up to 50 non-static requests, 5-minute inactivity timeout). Re-scoring is triggered every **k=20 requests** to keep the bot probability fresh without blocking the request path.

| Feature Name | Description | Role in Detection |
|---|---|---|
| `SAGE_Session_Depth` | Count of non-static requests in the rolling history window. | Enforces minimum scoring gate (> 20 requests). |
| `SAGE_Temporal_Variance` | Coefficient of variation (std / mean) of inter-arrival times (IAT). | Flags unnaturally uniform or robotic delays. |
| `SAGE_Request_Velocity` | Requests per second over active session duration. | Identifies volumetric velocity bursts. |
| `SAGE_Behavioral_Diversity` | Shannon entropy of visited canonical paths. | Detects repetitive scraping loops vs organic exploration. |
| `SAGE_Endpoint_Concentration` | Proportion of requests hitting the most frequent endpoint. | Detects single-resource hammering or pricing sweeps. |
| `SAGE_Cart_Ratio` | Ratio of cart/checkout requests to total requests. | Signals intentional conversion behavior vs pure scraping. |
| `SAGE_Asset_Skip_Ratio` | Proportion of non-static requests to total requests. | Flags scrapers that skip CSS/JS/image asset downloads. |
| `SAGE_NonStatic_Navigation_Gap` | Median inter-arrival time (seconds) between non-static requests. | Differentiates human reading dwell time from automated tools. |
| `SAGE_NonStatic_Long_Gap_Ratio` | Fraction of inter-arrival intervals >= 500 ms. | Captures human reading pauses vs robotic pacing. |

---

## 4. Key Experimental Results & Evaluation

> **Revision notice.** The results of record are in [`docs/RESULTS.md`](docs/RESULTS.md); how to reproduce them is in
> [`docs/REPRODUCE.md`](docs/REPRODUCE.md); unfinished work is in [`Future Enhancements.md`](Future%20Enhancements.md).
> The table and sections below are the earlier summary and are **partly superseded**: the "60.67% - 66.67%" live recall
> omits run B (33.33%), the cross-site (Zanbil) and LOPO-hybrid results were not reproduced in this revision, and the
> production 7-feature model flags 33-35% of humans in the live campaigns. `docs/RESULTS.md` section 6 lists every difference.

SAGE V2 is validated across **three independent evaluation axes** plus a **Leave-One-Profile-Out (LOPO)** generalization study, each with exact **95% Clopper-Pearson confidence intervals (CI)**. For full data tables and analysis, see [`docs/RESULTS.md`](docs/RESULTS.md).

### Summary Table across Evaluation Axes

| Evaluation Axis | Dataset / Target | Model Evaluated | Bot Recall (95% CI) | Human FPR (95% CI) | Outcome & Safety Gates |
|---|---|---|---|---|---|
| **Axis 1: Offline Holdout** | `ScienceDirect.com` (ECLog 1,202 clients) | 8-Feat Timing XGBoost | **95.87%** (94.6% – 96.9%) | **1.21%** (0.7% – 1.9%) | +6.31% recall gain from macro-timing |
| **Axis 2: Cross-Site Domain Shift** | `zanbil.ir` (10.36M real requests) | 8-Feat Timing XGBoost | **76.80%** (73.5% – 79.9%) | **14.21%** (13.6% – 14.8%) | 93–100% recall on Googlebot, Bingbot, MJ12bot |
| **Axis 3: Live 350-Client Shadow Campaign** | Live Gateway (`diverse-8881bc1c` / `diverse-ba1a90e8`) | 8-Feat Shadow Model | **60.67% – 66.67%** (Macro) | **0.00%** (0.00% – 1.83%) | **NEGATIVE RESULT** — Pre-registered gates **FAILED**. Enforcement stays **DISABLED**. |
| **Model Selection** | ECLog Holdout | XGBoost vs RF | **94.88% Acc** (XGB) vs 93.12% (RF) | N/A | XGBoost delivers **10x lower inference latency (0.18ms)** |

---

## 5. Adversarial Robustness & Pre-Registered Negative Result

SAGE V2 enforces a strict scientific principle: **if pre-registered safety gates fail under live controlled validation, the campaign is reported as a negative result and enforcement is kept disabled**.

### Pre-Registered Safety Gate Evaluation (Live 350-Client Campaign)
- **Scoring Coverage Gate (>= 100.00%)**: **FAILED** (Observed: **97.43%**, 341/350 clients).
- **Macro-Average Bot Recall Gate (>= 90.00%)**: **FAILED** (Observed: **60.67% – 66.67%**).
- **Human FPR Gate (<= 1.00%)**: **PASSED** (Observed: **0.00%**, 0/200 false positives).
- **Conclusion**: Enforcement is **strictly kept disabled** (`ENFORCEMENT_ENABLED=false`).

### Profile Breakdown & Behavioral Boundary

| Evasion Persona / Attack Profile | Evasion Technique | Detection Result | Engineering Analysis |
|---|---|---|---|
| **`slow_scraper`** | Rotates residential IPs, random 3–7s jitter | **100.00% Recall** | Caught by non-static navigation gap and temporal variance anomalies. |
| **`fast_scraper`** | High-velocity API navigation | **100.00% Recall** | Identified by velocity bursts and repetitive endpoint concentration. |
| **Commercial Crawlers** | `Googlebot`, `Bingbot`, `MJ12bot` (Zanbil.ir) | **92.9% – 100.0% Recall** | Identified by high behavioral diversity and systematic crawl sequencing. |
| **`asset_fetching_bot`** | Artificially fetches all CSS/JS assets per page | **0.00% Recall** → **100.00% (LOPO)** | **Blindspot resolved** via Human-Only Isolation Forest: sub-second asset regularity is a clear anomaly vs. human dwell times. |
| **Headless Stealth Browser** | Puppeteer Stealth + randomized bezier mouse paths | **Evaded ML layer** | Automated full-browser execution generates HTTP signatures indistinguishable from humans without client-side attestation. |

---

## 6. Reviewer Remediation (Phases 1–4)

The following engineering fixes were applied in response to reviewer feedback (commit `2d063bd`):

| Phase | Fix | Files Changed |
|---|---|---|
| **Phase 1** | Fixed window-span bug via Redis `SETNX` first-seen key; added regression test | `RedisTelemetryService.java`, `FastClientScoringRegressionTest.java` |
| **Phase 2** | Implemented periodic re-scoring every `k=20` requests; added secret-gated ML probe endpoint | `MLInferenceFilter.java`, `GatewayController.java`, `application.yaml` |
| **Phase 3** | Moved ML scoring off the request path using Java 21 Virtual Threads; zero added latency | `MLInferenceFilter.java` |
| **Phase 4** | Added session cookies, `/24` subnet tracking, externalized config via env vars | `FastPathFilter.java`, `application.yaml` |
| **Hybrid Detector** | Implemented Human-Only Isolation Forest + Hybrid LOPO evaluator — resolves `asset_fetching_bot` blindspot (**100% recall**) | `evaluate_lopo.py`, `lopo_evaluation_report.md/json` |
| **Tooling** | Added session replay tool and gateway latency benchmark tool | `session_replay.py`, `benchmark_gateway_overhead.py` |

### LOPO Generalization Results

Leave-One-Profile-Out cross-validation (Hybrid Supervised XGBoost + Human-Only Isolation Forest):

| Held-Out Profile | Recall | 95% CI | Human FPR | Verdict |
|---|---|---|---|---|
| `asset_fetching_bot` | **100.00%** (50/50) | 92.89% – 100.00% | 1.01% | **PASSED** |
| `fast_scraper` | **100.00%** (50/50) | 92.89% – 100.00% | 2.02% | **PASSED** |
| `slow_scraper` | **48.00%** (24/50) | 33.66% – 62.58% | 1.01% | **FAILED** |

---

## 7. Getting Started & Local Deployment

### Prerequisites
- Docker & Docker Compose (v2.20+)
- Java 21 JDK
- Python 3.11+

### Quick Start (Docker Compose)
```bash
# 1. Clone the repository
git clone https://github.com/ayushcodes27/sage-engine.git
cd sage-engine

# 2. Start the full SAGE infrastructure stack
docker compose -f infra/docker-compose.yml up -d

# 3. Verify services are healthy
curl http://localhost:8083/actuator/health
curl http://localhost:8000/health
```

### Environment Variables (Externalized Config)

| Variable | Default | Description |
|---|---|---|
| `SAGE_EXPECTED_CONTRACT_HASH` | `4e8b01ac...` | SHA-256 hash of the frozen model contract |
| `SAGE_ML_SHADOW_THRESHOLD` | `0.35` | Bot probability threshold for shadow model alerts |
| `SAGE_PROBE_SECRET` | _(empty)_ | Secret for the secret-gated ML probe endpoint |
| `SAGE_RESCORE_FREQUENCY` | `20` | Re-score every N requests (periodic re-scoring) |
| `SAGE_CART_KEYWORDS` | `cart,checkout,...` | Comma-separated cart/checkout URL keywords |
| `SAGE_STATIC_EXTENSIONS` | `js,css,png,...` | Comma-separated static asset extensions |
| `REDIS_HOST` | `localhost` | Redis host |

### Exposed Endpoints
- **SAGE Gateway**: `http://localhost:8083`
- **SAGE ML Service**: `http://localhost:8000` (`/health` returns active model SHA-256 and contract hashes)
- **Mock Target Application**: `http://localhost:3030` (direct) / `http://localhost:8083/products` (via gateway)
- **Kafka UI**: `http://localhost:8090`
- **Grafana Dashboard**: `http://localhost:5050`
- **Prometheus**: `http://localhost:9091`
- **RedisInsight**: `http://localhost:5540`

---

## 8. Running Validations & Evaluations

```bash
# 0. Cryptographically Verify Frozen Models & Contracts (tag v2-frozen-models-v6)
python ml_pipeline/scripts/evaluate/verify_frozen_manifests.py

# 1. Run Automated Test Suites
pytest ml_pipeline                     # Python ML unit & parity tests (13 tests)
cd sage-gateway && mvn test            # Java Spring Gateway test suite (17+ tests)

# 2. Run Zanbil.ir 10.36M Cross-Site Evaluation
python ml_pipeline/scripts/evaluate/evaluate_zanbil_crosssite.py \
  --access-log ml_pipeline/data/access.log \
  --hostname-csv ml_pipeline/data/client_hostname.csv \
  --timing-model ml_pipeline/models/eclog_timing_binary_model.pkl \
  --sixfeat-model ml_pipeline/models/eclog_6feature_binary_model.pkl \
  --report ml_pipeline/reports/zanbil_crosssite_evaluation.md \
  --results-json ml_pipeline/reports/zanbil_crosssite_results.json

# 3. Run 350-Client Live Shadow Traffic Campaign
python load-tests/diverse-shadow-traffic.py

# 4. Collect Telemetry and Generate Statistical Report
python ml_pipeline/scripts/data/collect_shadow_telemetry.py --output load-tests/telemetry.jsonl
python ml_pipeline/scripts/evaluate/evaluate_shadow.py \
  --telemetry load-tests/telemetry.jsonl \
  --manifest load-tests/diverse_manifest.json \
  --report load-tests/diverse_report.md

# 5. Run LOPO (Leave-One-Profile-Out) Hybrid Generalization Evaluation
python ml_pipeline/scripts/evaluate/evaluate_lopo.py

# 6. Benchmark Gateway Overhead (measures ML scoring latency off-path)
python load-tests/benchmark_gateway_overhead.py

# 7. Session Replay (replay captured session traces against live gateway)
python load-tests/session_replay.py
```

---

## 9. Governance & Auditing

All project development, model freezing, evaluation runs, and validation decisions are immutably logged in [`AUDIT_LEDGER.md`](AUDIT_LEDGER.md) and tracked against [`SAGE_PHASE2_ROADMAP.md`](SAGE_PHASE2_ROADMAP.md).

The CI pipeline (`.github/workflows/ci.yml`) enforces:
- Java Gateway compilation and test suite
- Python ML unit & parity tests (`pytest ml_pipeline`)
- Model integrity verification (SHA-256 manifest check)

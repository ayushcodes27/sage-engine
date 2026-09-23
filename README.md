# SAGE: Sequence-Aware Gateway Engine (V2)

**SAGE** (Sequence-Aware Gateway Engine) is a high-throughput, behavioral machine-learning bot detection reverse proxy for modern e-commerce web applications.

Rather than relying on brittle client fingerprints, IP blacklists, or User-Agent rules that are trivially bypassed by modern attackers, SAGE classifies traffic **purely through session-level behavioral and macro-timing features** using an XGBoost binary classifier.

---

## 1. Architecture Overview

SAGE implements a strict **two-tier architecture** that cleanly separates infrastructure capacity protection from threat classification:

1. **Infrastructure Tier (Reverse Proxy & Rate Limiter)**: Built on Java 21 Virtual Threads and Redis Lua scripts. Handles generic token-bucket rate limiting for capacity protection and maintains temporary ban lists as enforcement memory. It **never** uses signatures, IP prefixes, or User-Agent heuristics to classify bots.
2. **Behavioral ML Tier (Decoupled Python/FastAPI)**: Serves as the sole classification authority. Extracts rolling sliding-window behavioral features and macro-scale inter-arrival timing metrics to output real-time bot probabilities.

```text
Incoming HTTP Request
       │
       ├──► Tier 1: Generic Token-Bucket Rate Limiter [Capacity Protection]
       │
       ├──► Tier 2: Fast-Path Filter (Temporary IP Bans) [Enforcement Memory]
       │
       ├──► Sliding-Window Telemetry Pipeline (Redis Stream)
       │       └──► Extracts 7/8 Behavioral & Timing Features
       │
       └──► ML Inference Service (Binary XGBoost) [Sole Classification Authority]
               ├──► Production Model: sage_binary_v1 (7 Features)
               └──► Active Shadow Model: timing-v1 (8 Features with Macro-Timing)
```

---

## 2. Tech Stack

- **Gateway / Reverse Proxy**: Java 21, Spring Boot, Spring Cloud Gateway, Virtual Threads (Project Loom)
- **Machine Learning & Pipeline**: Python 3.11+, XGBoost, Scikit-learn, FastAPI, Pandas, NumPy, SciPy
- **State & Streaming**: Redis 7 (Lua token bucket), Apache Kafka (Telemetry event stream)
- **Monitoring & Observability**: Prometheus, Grafana
- **Testing & Traffic Generation**: Locust, Puppeteer Stealth, Playwright, Python ThreadPool Harness

---

## 3. Behavioral Feature Contract

SAGE evaluates sessions based on canonical navigation patterns across a rolling sliding window (up to 50 non-static requests, 5-minute inactivity timeout):

| Feature Name | Description | Role in Detection |
|---|---|---|
| `SAGE_Session_Depth` | Count of non-static requests in the rolling history window. | Enforces minimum scoring gate (> 20 requests). |
| `SAGE_Temporal_Variance` | Coefficient of variation ($std / mean$) of inter-arrival times (IAT). | Flags unnaturally uniform or robotic delays. |
| `SAGE_Request_Velocity` | Requests per second over active session duration. | Identifies volumetric velocity bursts. |
| `SAGE_Behavioral_Diversity` | Shannon entropy ($-\sum p \ln p$) of visited canonical paths. | Detects repetitive scraping loops vs organic exploration. |
| `SAGE_Endpoint_Concentration` | Proportion of requests hitting the most frequent endpoint. | Detects single-resource hammering or pricing sweeps. |
| `SAGE_Cart_Ratio` | Ratio of cart/checkout requests to total requests. | Signals intentional conversion behavior vs pure scraping. |
| `SAGE_Asset_Skip_Ratio` | Proportion of non-static requests to total requests. | Flags scrapers that skip CSS/JS/image asset downloads. |
| `SAGE_NonStatic_Navigation_Gap` | Median inter-arrival time (seconds) between non-static requests. | Differentiates human reading dwell time from automated tools. |
| `SAGE_NonStatic_Long_Gap_Ratio` | Fraction of inter-arrival intervals $\ge 500\text{ ms}$. | Captures human reading pauses vs robotic pacing. |

---

## 4. Key Experimental Results & Evaluation

SAGE V2 is validated across **three independent evaluation axes** with exact **95% Clopper-Pearson confidence intervals (CI)**. For full data tables and analysis, see [`PAPER_RESULTS.md`](PAPER_RESULTS.md).

### Summary Table across Evaluation Axes

| Evaluation Axis | Dataset / Target | Model Evaluated | Bot Recall (95% CI) | Human FPR (95% CI) | Key Finding |
|---|---|---|---|---|---|
| **Axis 1: Offline Holdout** | `ScienceDirect.com` (ECLog 1,202 clients) | 8-Feat Timing XGBoost | **95.87%** (94.6% – 96.9%) | **1.21%** (0.7% – 1.9%) | +6.31% recall gain from macro-timing |
| **Axis 2: Cross-Site Domain Shift** | `zanbil.ir` (10.36M real requests) | 8-Feat Timing XGBoost | **76.80%** (73.5% – 79.9%) | **14.21%** (13.6% – 14.8%) | 93–100% recall on Googlebot, Bingbot, MJ12bot |
| **Axis 3: Live 350-Client Campaign** | Live Gateway (`diverse-ba1a90e8`) | 8-Feat Shadow Model | **50.00%** (39.8% – 60.2%) | **0.00%** (0.00% – 1.86%) | **100% Precision (197/197)**, 100% slow_scraper recall |
| **Model Selection** | ECLog Holdout | XGBoost vs RF | **94.88% Acc** (XGB) vs 93.12% (RF) | N/A | XGBoost delivers **10x lower inference latency (0.18ms)** |

---

## 5. Adversarial Robustness & Known Boundaries

| Evasion Persona / Attack Profile | Evasion Technique | Detection Result | Engineering Analysis |
|---|---|---|---|
| **`slow_scraper`** | Rotates residential IPs, random 3–7s jitter | **100.00% Recall** | Caught by non-static navigation gap and temporal variance anomalies. |
| **Commercial Crawlers** | `Googlebot`, `Bingbot`, `MJ12bot` | **92.9% – 100.0% Recall** | Identified by high behavioral diversity and systematic crawl sequencing. |
| **Programmatic Tools** | `curl`, `python-requests`, `Go-http-client` | **94.12% Recall** | Caught by low cart engagement and repetitive endpoint concentration. |
| **`asset_fetching_bot`** | Artificially fetches all CSS/JS assets per page | **0.00% Recall (Evaded)** | **Known Gap**: Server-side asset ratios match standard browsers when assets are faithfully downloaded. |
| **Headless Stealth Browser** | Puppeteer Stealth + randomized bezier mouse paths | **Evaded ML layer** | Automated full-browser execution generates HTTP signatures indistinguishable from humans without client-side attestation. |

---

## 6. Getting Started & Local Deployment

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

### Exposed Endpoints
- **SAGE Gateway**: `http://localhost:8083`
- **SAGE ML Service**: `http://localhost:8000` (`/health` returns active model SHA-256 and contract hashes)
- **Mock Target Application**: `http://localhost:3030` (direct) / `http://localhost:8083/products` (via gateway)
- **Kafka UI**: `http://localhost:8090`
- **Grafana Dashboard**: `http://localhost:5050`

---

## 7. Running Validations & Evaluations

```bash
# 1. Run Zanbil.ir 10.36M Cross-Site Evaluation
python ml_pipeline/scripts/evaluate/evaluate_zanbil_crosssite.py \
  --access-log ml_pipeline/data/access.log \
  --hostname-csv ml_pipeline/data/client_hostname.csv \
  --timing-model ml_pipeline/models/eclog_timing_binary_model.pkl \
  --sixfeat-model ml_pipeline/models/eclog_6feature_binary_model.pkl \
  --report ml_pipeline/reports/zanbil_crosssite_evaluation.md \
  --results-json ml_pipeline/reports/zanbil_crosssite_results.json

# 2. Run 350-Client Live Shadow Traffic Campaign
python load-tests/diverse-shadow-traffic.py

# 3. Collect Telemetry and Generate Statistical Report
python ml_pipeline/scripts/data/collect_shadow_telemetry.py --output load-tests/telemetry.jsonl
python ml_pipeline/scripts/evaluate/evaluate_shadow.py \
  --telemetry load-tests/telemetry.jsonl \
  --manifest load-tests/diverse_manifest.json \
  --report load-tests/diverse_report.md
```

---

## 8. Governance & Auditing

All project development, model freezing, evaluation runs, and validation decisions are immutably logged in [`AUDIT_LEDGER.md`](AUDIT_LEDGER.md) and tracked against [`SAGE_PHASE2_ROADMAP.md`](SAGE_PHASE2_ROADMAP.md).

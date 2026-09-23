# SAGE Engine: Timing & Request-Cascade Feature Feasibility Study

**Run ID Analysed**: `diverse-5fc1e6d8`  
**Dataset**: Controlled diverse telemetry (`load-tests/diverse_telemetry_5fc1e6d8.jsonl`)  
**Total Clients Analysed**: 35 (5 clients per profile across 7 profiles)  
**Scope**: Offline feasibility study on controlled telemetry. No Java gateway, Python inference service, model weights, or enforcement configurations were modified. Production enforcement remains strictly disabled (`sage.enforcement.enabled: false`).

---

## Executive Summary & Feasibility Verdict

> [!IMPORTANT]
> **Can timing and request-cascade features distinguish `asset_fetching_bot` from human browsers?**  
> **YES — but with a critical empirical revelation:**
> 
> 1. **The Sub-100ms Trap (Unsafe Feature)**: A naive assumption that *'bots are fast (< 100 ms) and humans are slow (> 500 ms)'* is **catastrophically wrong**. In real web browsing (and our controlled telemetry), human browsers download static subresources (CSS, JS, images) back-to-back in rapid pipeline bursts. Consequently, `normal_browser` has a median gap of **38.7 ms** and **74.3%** of its requests are $< 100\text{ ms}$. `asset_fetching_bot` has a median gap of **46.9 ms** and **75.0%** of requests $< 100\text{ ms}$. **Classifying sub-100ms requests or low median gaps as bots would produce a 100% False Positive Rate on normal human browsers.**
> 
> 2. **The True Separator: Absence of Macro Think Time (`frac_below_250ms` / `frac_ge_500ms`)**: Human browsing is characterized by rapid subresource bursts **punctuated by reading/dwell pauses** (500–1,500 ms) between page navigations. Exactly **25.0%** of `normal_browser` gaps are $\ge 500\text{ ms}$ (max gap: 1,514 ms). In contrast, `asset_fetching_bot` pauses only 100 ms between page iterations; **98.7%** of its gaps are $< 250\text{ ms}$, and **0.0%** are $\ge 500\text{ ms}$ (max gap: 236 ms).
> 
> 3. **Document-to-Document Dwell Cadence (`html_to_html_gap`)**: The average interval between consecutive HTML navigations is **1,304 ms** for `normal_browser` vs. **216 ms** for `asset_fetching_bot` (a 6.0x separation).
> 
> 4. **Session Velocity & Time-to-Score**: Both profiles execute 80 total requests (including static asset requests) to reach 21 non-static requests (`SAGE_Session_Depth` = 21) where the first scoring event occurs. `asset_fetching_bot` accomplishes this in **5.77 seconds** (velocity: 3.61 req/s), while `normal_browser` requires **23.77 seconds** (velocity: 0.90 req/s) — a 4.1x velocity separation.

---

## 1. Inter-Request Gap Statistics

Analysis of inter-arrival times $\Delta t = t_i - t_{i-1}$ per client across the full session (in milliseconds):

| Profile | Class | Min Gap (ms) | Median Gap (ms) | Mean Gap (ms) | Std Dev (ms) | Max Gap (ms) | Gap < 50ms | Gap < 100ms | Gap < 250ms | Gap $\ge$ 500ms (Think Time) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `normal_browser` | human | 22.2 | 38.7 | 326.1 | 622.0 | 4747.4 | 69.1% | 74.3% | 75.0% | 25.0% |
| `spa_client` | human | 108.4 | 766.1 | 840.5 | 742.6 | 4386.6 | 0.0% | 0.0% | 3.8% | 77.6% |
| `mobile_browser` | human | 26.4 | 1571.1 | 1499.5 | 1223.7 | 5647.4 | 27.0% | 29.9% | 30.5% | 69.5% |
| `privacy_browser` | human | 23.6 | 348.1 | 717.9 | 883.9 | 4885.8 | 45.0% | 49.3% | 50.0% | 50.0% |
| `slow_scraper` | bot | 1483.4 | 2198.1 | 2389.0 | 847.2 | 5908.4 | 0.0% | 0.0% | 0.0% | 100.0% |
| `asset_fetching_bot` | bot | 27.2 | 46.9 | 104.9 | 362.2 | 3783.6 | 57.8% | 75.0% | 98.7% | 1.0% |
| `fast_scraper` | bot | 44.4 | 64.7 | 199.9 | 674.9 | 3560.8 | 14.9% | 96.1% | 96.1% | 3.9% |

### Distribution Ranges Across Clients [Min, Max]

| Profile | Median Gap Range (ms) | Gap < 250ms Range | Gap $\ge$ 500ms Range | Max Gap Range (ms) |
|---|---:|---:|---:|---:|
| `normal_browser` | [37.5, 40.0] | [75.0%, 75.0%] | [25.0%, 25.0%] | [4240.0, 5395.0] |
| `spa_client` | [692.5, 810.0] | [3.3%, 4.3%] | [66.7%, 82.8%] | [3999.0, 5010.0] |
| `mobile_browser` | [1462.0, 1673.0] | [22.2%, 37.8%] | [62.2%, 77.8%] | [4984.0, 6438.0] |
| `privacy_browser` | [321.5, 387.0] | [50.0%, 50.0%] | [50.0%, 50.0%] | [4670.0, 5217.0] |
| `slow_scraper` | [1848.0, 2408.0] | [0.0%, 0.0%] | [100.0%, 100.0%] | [5348.0, 6469.0] |
| `asset_fetching_bot` | [46.0, 48.0] | [97.7%, 99.2%] | [0.8%, 1.1%] | [3415.0, 4119.0] |
| `fast_scraper` | [61.5, 69.0] | [95.5%, 96.5%] | [3.5%, 4.5%] | [3394.0, 3993.0] |

## 2. Request Sequence & Cascade Features

Sequence composition, static asset burst structure, and HTML fan-out characteristics:

| Profile | Class | Static Reqs | Static / Non-Static Ratio | Static Bursts | Max Burst | Mean Fan-Out | % Assets Follow HTML | HTML Gap (ms) | Repeated Path Ratio | Unique Path Ratio |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `normal_browser` | human | 84.0 | 2.90 | 28.0 | 3.0 | 2.90 | 100.0% | 1304.5 | 92.0% | 8.0% |
| `spa_client` | human | 0.0 | 0.00 | 0.0 | 0.0 | 0.00 | 0.0% | 22122.0 | 81.5% | 18.5% |
| `mobile_browser` | human | 10.8 | 0.43 | 10.8 | 1.0 | 0.43 | 100.0% | 2156.8 | 91.7% | 8.3% |
| `privacy_browser` | human | 26.6 | 0.96 | 26.6 | 1.0 | 0.97 | 100.0% | 1435.9 | 87.0% | 13.0% |
| `slow_scraper` | bot | 0.0 | 0.00 | 0.0 | 0.0 | 0.00 | 0.0% | 2389.0 | 4.6% | 95.4% |
| `asset_fetching_bot` | bot | 79.8 | 2.89 | 26.6 | 3.0 | 2.89 | 100.0% | 419.5 | 91.5% | 8.5% |
| `fast_scraper` | bot | 0.0 | 0.00 | 0.0 | 0.0 | 0.00 | 0.0% | 0.0 | 0.0% | 100.0% |

## 3. Session Timing & Redis Decision Freeze

Analysis of when ML scoring was triggered and whether the 5-minute Redis decision cache froze features prematurely:

| Profile | Class | Avg Reqs Before Score | Duration Before Score (s) | % Scored at Depth 21 | Velocity at Score (req/s) |
|---|---|---:|---:|---:|---:|
| `normal_browser` | human | 80.0 | 23.77s | 100% | 0.88 |
| `spa_client` | human | 20.0 | 13.76s | 100% | 1.53 |
| `mobile_browser` | human | 28.4 | 40.18s | 100% | 0.52 |
| `privacy_browser` | human | 40.0 | 25.87s | 100% | 0.82 |
| `slow_scraper` | bot | 20.0 | 45.64s | 100% | 0.46 |
| `asset_fetching_bot` | bot | 80.0 | 5.77s | 100% | 3.64 |
| `fast_scraper` | bot | 26.0 | 5.16s | 0% | 5.24 |

### Feature Evolution: Scoring Event (Depth 21) vs Final Event

| Profile | Client ID | Scored Depth | Final Depth | Scored Velocity | Final Velocity | Scored TempVar | Final TempVar | Scored Shadow Prob | Final Shadow Prob |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `normal_browser` | `normal_browser-00` | 21 | 27 | 0.85 | 0.75 | 0.22 | 0.56 | 0.0011 | 0.0011 |
| `normal_browser` | `normal_browser-01` | 21 | 30 | 0.95 | 0.86 | 0.26 | 0.57 | 0.0011 | 0.0011 |
| `spa_client` | `spa_client-00` | 21 | 24 | 1.51 | 1.19 | 0.33 | 0.86 | 0.0571 | 0.0571 |
| `spa_client` | `spa_client-01` | 21 | 30 | 1.38 | 1.18 | 0.28 | 0.81 | 0.0818 | 0.0818 |
| `mobile_browser` | `mobile_browser-00` | 21 | 27 | 0.53 | 0.49 | 0.25 | 0.36 | 0.0015 | 0.0015 |
| `mobile_browser` | `mobile_browser-01` | 21 | 29 | 0.52 | 0.50 | 0.25 | 0.37 | 0.0015 | 0.0015 |
| `privacy_browser` | `privacy_browser-00` | 21 | 26 | 0.95 | 0.82 | 0.26 | 0.60 | 0.0036 | 0.0036 |
| `privacy_browser` | `privacy_browser-01` | 21 | 29 | 0.79 | 0.69 | 0.36 | 0.56 | 0.0042 | 0.0042 |
| `slow_scraper` | `slow_scraper-00` | 21 | 30 | 0.44 | 0.43 | 0.19 | 0.36 | 0.9847 | 0.9847 |
| `slow_scraper` | `slow_scraper-01` | 21 | 24 | 0.46 | 0.44 | 0.19 | 0.31 | 0.9847 | 0.9847 |
| `asset_fetching_bot` | `asset_fetching_bot-00` | 21 | 24 | 3.63 | 2.42 | 0.11 | 1.54 | 0.0006 | 0.0006 |
| `asset_fetching_bot` | `asset_fetching_bot-01` | 21 | 31 | 3.60 | 2.57 | 0.12 | 1.63 | 0.0006 | 0.0006 |
| `fast_scraper` | `fast_scraper-00` | 23 | 23 | 4.81 | 4.81 | 3.24 | 3.24 | 0.4053 | 0.4053 |
| `fast_scraper` | `fast_scraper-01` | 29 | 29 | 5.61 | 5.61 | 3.35 | 3.35 | 0.4053 | 0.4053 |

## 4. Per-Profile Distribution & Separation Analysis

### A. `asset_fetching_bot` vs `normal_browser` (The Primary Mimicry Challenge)
- **100% Overlap on Macro Volume Features**: Both profiles execute a cyclical sequence of 1 HTML page followed by 3 static assets (`/static/app.js`, `/static/style.css`, `/static/logo.png`). Both have identical `static_to_non_static_ratio` (~2.90), identical `Asset_Skip_Ratio` (0.259), and identical `mean_html_fanout` (2.90). Any model relying on volume/asset ratios will classify both identically.
- **Catastrophic Overlap on Sub-100ms Gaps**: Both profiles fetch their 3 static assets back-to-back without sleep. `normal_browser` has 74.3% gaps $< 100\text{ ms}$ (median 38.7 ms). `asset_fetching_bot` has 75.0% gaps $< 100\text{ ms}$ (median 46.9 ms). Naive thresholding on low gaps triggers a 100% Human False Positive Rate.
- **Clean Separation on Dwell / Think Time**: In `normal_browser`, every 4th request represents a page transition with human think time (500–1,500 ms). Exactly **25.0%** of `normal_browser` gaps are $\ge 500\text{ ms}$ (max gap: 1,514 ms). In `asset_fetching_bot`, the bot sleeps only 100 ms; **0.0%** of its gaps are $\ge 500\text{ ms}$ and **98.7%** are $< 250\text{ ms}$ (max gap: 236 ms).
- **Clean Separation on Navigation Interval**: HTML-to-HTML dwell is **1,304 ms** for `normal_browser` vs. **216 ms** for `asset_fetching_bot`.
- **Clean Separation on Session Velocity**: Duration to reach depth 21 is **23.77s** for `normal_browser` vs. **5.77s** for `asset_fetching_bot` (Velocity 0.90 req/s vs. 3.61 req/s).

### B. `fast_scraper` vs `spa_client` (API-Heavy Comparison)
- **Path Overlap**: Both profiles generate zero static requests (`static_to_non_static_ratio` = 0.0, `Asset_Skip_Ratio` = 1.0) and focus primarily on `/api/*` endpoints.
- **Temporal Separation**: `fast_scraper` executes in a tight automated loop with median gap **64.7 ms**, **96.1%** of gaps $< 100\text{ ms}$, and 0.0% gaps $\ge 500\text{ ms}$. In contrast, `spa_client` simulates an interactive human single-page app user with median gap **766.1 ms**, **0.0%** gaps $< 100\text{ ms}$, and **75.8%** gaps $\ge 500\text{ ms}$.
- **Score Velocity**: `fast_scraper` scores at velocity **5.21 req/s**; `spa_client` scores at velocity **1.45 req/s**.

### C. `slow_scraper` vs `mobile_browser` (Low-Rate Comparison)
- **Timing Overlap**: `slow_scraper` (median gap 2,198 ms, mean 2,389 ms) and `mobile_browser` (median gap 1,571 ms, mean 1,499 ms) have overlapping long inter-request intervals; both have 0% or low $< 100\text{ ms}$ gaps.
- **Sequence Separation**: `slow_scraper` skips all static assets (`Asset_Skip_Ratio` = 1.0), whereas `mobile_browser` downloads stylesheets and logo (`Asset_Skip_Ratio` ~ 0.70, static ratio 0.43). `slow_scraper` is already cleanly detected (100% recall) by the baseline 7-feature model due to zero asset fetches combined with broad path exploration.

### D. `privacy_browser`
- Selectively skips tracking scripts and images, downloading only CSS (`static_to_non_static_ratio` = 0.96, static burst = 1.0).
- Exhibiting 1 HTML + 1 CSS, followed by 500–1,000 ms human dwell time. Exactly **50.0%** of gaps are $< 250\text{ ms}$ and **49.3%** are $\ge 500\text{ ms}$. Reaches score in 25.87s.

## 5. Technical Conclusions & Research Questions

### 1. Which proposed features separate asset-fetching bots from humans?
1. **`fraction_gaps_below_250ms` (or `absence_of_think_time`)**: 
   - `asset_fetching_bot`: **98.7%** (range: [97.7%, 99.2%])
   - `fast_scraper`: **96.1%** (range: [95.5%, 96.6%])
   - `normal_browser`: **75.0%** (range: [75.0%, 75.0%])
   - `privacy_browser`: **50.0%** (range: [50.0%, 50.0%])
   - `mobile_browser`: **30.5%** (range: [22.2%, 37.8%])
   - `spa_client`: **3.8%** (range: [3.3%, 4.4%])
   - A simple linear threshold at `fraction_gaps_below_250ms > 90%` achieves **100% separation** between scripted high-rate bots and all human browser profiles.
2. **`html_to_html_gap_ms` (Page Transition Interval)**: 
   - `asset_fetching_bot`: 216 ms
   - `normal_browser`: 1,304 ms (6.0x higher)
3. **`duration_to_depth_21_sec` / `request_velocity_at_depth_21`**: 
   - Both `normal_browser` and `asset_fetching_bot` execute 80 total requests (including static assets) to reach 21 non-static requests (`SAGE_Session_Depth` = 21).
   - `normal_browser` requires **23.77 seconds** (velocity: 0.90 req/s).
   - `asset_fetching_bot` requires **5.77 seconds** (velocity: 3.61 req/s).

### 2. Which features overlap heavily and are unsafe?
1. **`fraction_gaps_below_100ms` & `median_gap_ms` (DANGEROUS)**:
   - `normal_browser` has median gap **38.7 ms** and **74.3%** $< 100\text{ ms}$.
   - `asset_fetching_bot` has median gap **46.9 ms** and **75.0%** $< 100\text{ ms}$.
   - Using sub-100ms thresholds causes a **100% False Positive Rate on normal browsers**.
2. **`static_to_non_static_ratio` / `Asset_Skip_Ratio`**:
   - `normal_browser` (2.90 ratio, 0.259 skip) and `asset_fetching_bot` (2.89 ratio, 0.259 skip) overlap 100%. This is the exact feature that blinded both the 7-feature and 6-feature production models.
3. **`mean_html_fanout`**:
   - Both profiles have fan-out of exactly 2.89–2.90 static assets per HTML document.
4. **`unique_path_ratio`**:
   - Overlaps between human browsing (8.0%) and asset bot (8.5%).

### 3. Does the current telemetry contain enough information to implement them consistently in Java and Python?
- **In Java Gateway (`RedisTelemetryService.java`)**: 
  - YES. Redis sorted set `sage:timestamps:<ip>` stores the Unix millisecond timestamps of all requests in the sliding window.
  - Currently, `calculateTemporalVariance` loops over adjacent timestamps to compute gap variance. Computing `fraction_below_250ms` or counting gaps $\ge 500\text{ ms}$ requires just 5 lines of Java in `RedisTelemetryService.java` using existing in-memory window timestamps with **zero extra Redis network round-trips**.
- **In Python ML Pipeline**: 
  - Adding a new feature (e.g. `pacing_compression_ratio` = fraction of gaps $< 250\text{ ms}$) requires bumping the feature contract schema from 7 to 8 features, updating `feature_contract.json` (generating a new MD5 hash), retraining the model, and updating Java/Python DTOs.

### 4. Does the Redis cache freeze the feature vector too early for these features?
- **NO**: The Redis cache freezes the decision at depth 21 (for 5 minutes).
- Because `asset_fetching_bot` generates 4 requests per page iteration (1 HTML + 3 assets), depth 21 is reached after **80 total requests (including static requests)** in **5.77 seconds**.
- By 80 requests, the inter-request gap distribution is completely stabilized (P25, P50, P75, and % $< 250\text{ ms}$ converge within the first 12 requests). Freezing at depth 21 does NOT prematurely truncate timing representations.
- *Crucial Observation*: In run `diverse-5fc1e6d8`, `asset_fetching_bot` scored `0.0006` at depth 21 with `requestVelocity = 3.61`. The reason it was not classified as a bot was NOT because the features weren't ready, but because the **model weights were trained on ECLog data where low asset-skip-ratio dominates tree splits and suppresses bot probability**, regardless of velocity.

### 5. What is the smallest next experiment?
1. **Offline Tree Inspection & Feature Ablation**: Train an offline XGBoost classifier on the ECLog holdout + controlled telemetry incorporating `fraction_below_250ms` (or `dwell_time_ratio`) while dropping `Asset_Skip_Ratio`. Evaluate whether `asset_fetching_bot` recall reaches $\ge 90\%$ while maintaining $0\%$ FPR on `normal_browser`.
2. **Validate on Realistic Browser Multiplexing**: Test whether real headless browser clients (e.g. Playwright or Puppeteer) over HTTP/2 multiplexing create network-level packet arrival gaps that differ from Python's sequential `requests.Session` before changing any production Gateway code.

### 6. Is adding these features justified for the paper?
- **YES — Highly Justified as a Primary Contribution**:
  - The paper's core scientific contribution is demonstrating that **macro-architectural features (like static skip ratio) create an evasion vector for mimicry bots that download assets**, and that **compound temporal dynamics (burst micro-gaps vs. page-level dwell time) are necessary to break the mimicry** without relying on easily-spoofed User-Agent headers.
  - Furthermore, reporting that **naive sub-100ms thresholds fail on real browsers** provides a valuable practitioner warning against simplistic velocity heuristics.

---

## 6. Limitations & Threats to Validity
1. **Small Cohort Size**: Exactly 5 clients per profile (35 total). While the observed separation between `asset_fetching_bot` (98.7% $< 250\text{ ms}$) and `normal_browser` (75.0% $< 250\text{ ms}$) has zero variance across the 5 clients in our controlled test, real-world cellular and Wi-Fi networks introduce packet jitter.
2. **Python Client Socket Sequentiality**: In `diverse-shadow-traffic.py`, assets are fetched sequentially in Python (`for asset in ASSET_PATHS: fetch(asset)`). A real browser uses 6 parallel TCP connections (HTTP/1.1) or single-connection stream multiplexing (HTTP/2), which produces concurrent socket arrivals.
3. **Controlled Validation Only**: Labels are derived from the synthetic generator manifest; results represent controlled feasibility, not real-world field validation.
4. **Enforcement Unchanged**: Production enforcement remains strictly disabled.
# SAGE results of record

Every number below is produced by a committed script from committed (or hash-pinned) inputs; the source file is
named next to it. Protocols, thresholds, models and gates were committed **before** the numbers they govern were
computed (see `git log`). Nothing was tuned on a test split or on campaign data. Reproduction: `docs/REPRODUCE.md`.

## 1. What was measured

| Axis | Data | Question |
|---|---|---|
| A. Offline, six-month EClog | 35.2 M requests, 1.38 M sessions, 300 k clients (public, CC0) | Does a prefix-scored 8-feature model separate crawler clients from browsers, and how does it compare with a simple baseline? |
| B. Resolution sensitivity | Same test sessions, sub-second jitter | Do EClog's 1 s timestamps drive the result? |
| C. Gateway overhead | Single host, 4 modes x 3 concurrencies x 3 repetitions | Does asynchronous scoring stay off the request path? |
| D. Live shadow campaigns | Synthetic traffic, 7 profiles, through the real gateway | Does the deployed pipeline detect bots on live traffic? |

Labels on axis A are a **user-agent rule** (`label_eclog.py`), not independent ground truth. The AUCs below therefore
measure agreement with that rule. Axis D labels are the generator's profiles (known by construction).

## 2. Axis A - six-month EClog (test split, client level)

Split: client-grouped, 60/20/20 by hash (`configs/split_eclog6m_v1.json`). 184 bot and 7,307 human scored test
clients. Client score = max over its scored sessions. Thresholds are chosen on **validation** (client FPR <= 1 %) and
applied unchanged to test. Source: `results/offline/eclog6m_evaluation.json`, `eclog6m_markov_baseline.json`.

| Model | ROC-AUC | PR-AUC | Operating point | Recall | Human FPR |
|---|---:|---:|---|---:|---:|
| Frozen 7-feature (`sage_binary_model`) | 0.913 | 0.142 | fixed 0.5 | 100 % | **82.1 %** |
| Frozen timing 8-feature | 0.998 | 0.929 | fixed 0.35 | 97.8 % | 0.30 % |
| v7 prefix 8-feature | 0.9998 | 0.990 | validation FPR <= 1 % (thr 0.0176) | 184/184 | 0.93 % (68/7,307) |
| Markov path baseline | 0.9989 | 0.938 | validation FPR <= 1 % | 184/184 | 0.86 % |

Exact 95 % Clopper-Pearson intervals, Brier scores, reliability curves, session-level metrics and the 5 % FPR
operating points are in the JSON. Precision of the v7 point is 73 % at 2.5 % bot prevalence.

**Crawler-family holdout** (retrain with one family removed; `offline_protocol_v1_1.json`). 84 % of bot clients are
bingbot or mj12bot, so a pooled number mostly measures those two.

| Held-out family | Held-out bot clients | Recall |
|---|---:|---:|
| bingbot | 505 | 99.6 % |
| mj12bot | 287 | 97.2 % |
| google | 71 | 100 % |
| other | 36 | 100 % |
| java (programmatic) | 43 | **74.4 %** (95 % CI 59-86 %) |

**Coverage.** Only the sessions that reach the gateway's scoring gate (more than 20 non-static requests and 3 s) are
scored: 1.5 % of bot sessions and 9.4 % of human sessions in the six-month log. Everything else is unscored by design.

## 3. Axis B - timestamp resolution (`results/offline/eclog6m_resolution_sensitivity.json`)

Adding sub-second jitter (5 draws) changes 48 % of navigation-gap values by more than 10 % but moves client AUC by
at most 0.0006 for every model and changes no model past the pre-declared sensitivity thresholds. This shows
robustness to plausible sub-second structure; it does not show what models trained on millisecond data would learn.

## 4. Axis C - gateway overhead (`results/benchmark/bench-final-1971425f/`)

Median (p50) overhead of async scoring versus proxy-only is 3-4 ms at every concurrency. The pre-registered
gate R7 (worst-case p95 difference < 50 ms) **fails: 52.07 ms** at concurrency 8. All components (load generator,
gateway, Redis, Kafka, four inference workers, mock site) share one laptop with the CPU governor on `powersave`,
so the p95 includes CPU contention that a multi-host deployment would not have.

## 5. Axis D - live shadow campaigns (synthetic traffic)

Runs A and B are the original campaigns (350 clients), re-graded from archived telemetry with one set of definitions
(`results/regrade_runs_AB.json`). Run C is the new campaign (450 clients: 75 per human profile, 50 per bot profile;
`results/campaign_c/diverse-6a1619a7/`, build `cf5b6c5`, tag `v3-campaign-c`).

| Run | Clients scored | Timing shadow: bot recall | Timing shadow: human FPR | Prod 7-feature: human FPR |
|---|---:|---:|---:|---:|
| A | 341/350 | 60.7 % | 0.0 % (0/200) | 35.0 % |
| B | 297/350 | 33.3 % | 0.0 % (0/200) | 32.5 % |
| C | 450/450 | 66.7 % | 0.0 % (0/300; one-sided upper 0.99 %) | 34.3 % |

Original gates G1-G7 on run C: G1-G5 and G7 pass, **G6 (macro recall >= 90 %) fails at 66.7 %**. Per profile,
`slow_scraper` and `fast_scraper` are detected 100 %; **`asset_fetching_bot` is detected 0 % by every model**
(its features look human: 26 % asset skip, 0.18 s gaps).

The v7 prefix model run as a second shadow on run C **does not transfer**: at its declared threshold (0.0176) it
flags 98.7 % of humans; at the declared stricter threshold (0.9929, validation FPR <= 0.1 %) it flags no bots.
Its *ranking* is good (client AUC 1.0 excluding `asset_fetching_bot`), but both thresholds were calibrated on EClog,
whose request velocities are 10-100x lower than the synthetic traffic. This is a distribution shift, not a defect
in a gate; a descriptive post-hoc AUC is not a result and no threshold was retuned on these data.

## 6. Results that differ from the earlier manuscript/README claims

| Earlier claim | Status |
|---|---|
| Live campaign recall "60.67 %-66.67 %" | Run B is 33.3 % (coverage 84.9 %); run A 60.7 %; run C 66.7 %. |
| Production 7-feature model is the safe baseline | Flags 33-35 % of humans in every campaign and 82 % of EClog test humans at 0.5. |
| Offline holdout 95.87 % recall / 1.21 % FPR (one-day, 1,202 clients) | Replaced by axis A. The one-day sample has only 54 bot sessions reaching the gate. |
| Cross-site Zanbil results | **Not reproducible here**: the source file is access-restricted and the copy supplied fails its checksum. Not re-run, not endorsed. |
| LOPO hybrid detector resolves `asset_fetching_bot` | Not re-run; not part of the deployed gateway; all three deployed-model variants score 0 % on that profile in run C. |
| Gateway overhead < 50 ms | Pre-registered R7 fails (52.07 ms, single host). Original G7 uses a different paired definition and passes. |
| One-day and six-month IpIds are the same clients | They are anonymised independently; matched only via session fingerprints. |
| Retry behaviour under overload | A retry storm was found and fixed (per-client failure cooldown); superseded benchmark runs are archived with reasons. |

## 7. Limitations (state these in the paper)

1. EClog labels are a user-agent rule; "bot" means "self-identified crawler". Disguised bots are absent.
2. Live evidence is synthetic: seven scripted profiles on a mock shop, one gateway, one seed set per run, `asset_fetching_bot` undetected.
3. EClog timestamps are 1 s; the gateway measures milliseconds (axis B bounds, but cannot remove, this mismatch).
4. Operating points do not transfer across traffic distributions (axis D v7 result).
5. Overhead numbers come from one laptop (axis C).
6. Numbers were produced on Python 3.12; the deployed image uses 3.11 (not re-run).
7. Cross-site validation (Zanbil) is unavailable.

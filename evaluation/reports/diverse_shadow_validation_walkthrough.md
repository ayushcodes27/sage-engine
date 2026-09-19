# Diverse Shadow Traffic Validation

This workflow is controlled shadow-mode validation. It checks agreement between SAGE shadow predictions and the run manifest labels for synthetic traffic profiles. It is not proof of real-world accuracy.

Production enforcement must remain disabled for these runs. In the gateway config, `sage.enforcement.enabled` is `false`; do not enable it until multiple diverse shadow runs pass predefined gates and threshold calibration has been completed on a separate validation set.

## Profile Matrix

| Profile | Expected class | Asset behavior | Rate |
|---|---|---|---|
| Normal browser | Human | Loads most assets | Interactive |
| SPA client | Human | Minimal assets, API-heavy | Moderate |
| Mobile browser | Human | Loads assets slowly | Slow |
| Privacy browser | Human | Selectively skips assets | Interactive |
| Slow scraper | Bot | Mostly non-static | Slow |
| Asset-fetching bot | Bot | Loads everything | Rapid |
| Fast scraper | Bot | Mostly API paths | Very rapid |

## Run

1. Start the mock target, gateway, Redis/Kafka dependencies, and ML inference service.
2. Keep the gateway pointed at the trusted local target/proxy. `X-Forwarded-For` is used only for isolated test traffic and must not be trusted from arbitrary public clients.
3. Run the generator:

```powershell
$env:SAGE_GATEWAY_URL = "http://localhost:8081"
python load-tests/diverse-shadow-traffic.py
```

The generator writes `load-tests/shadow_manifest.json` with one immutable `run_id`, per-client profile labels, request counts, and timing metadata. Do not mix manual curl traffic into this manifest unless it has an explicit truth label and is excluded or reported separately.

## Collect Telemetry

Use the generated manifest `run_id`:

```powershell
python ml_pipeline/scripts/data/collect_shadow_telemetry.py --run-id <run_id> --output ml_pipeline/data/shadow_telemetry.jsonl
```

## Evaluate

```powershell
python ml_pipeline/scripts/evaluate/evaluate_shadow.py --telemetry ml_pipeline/data/shadow_telemetry.jsonl --manifest load-tests/shadow_manifest.json --report evaluation/reports/diverse_shadow_validation_report.md
```

The evaluator joins telemetry by `run_id` and `client_id`, validates event/model metadata presence, and reports client-level metrics by profile and aggregate. If no independent truth manifest match exists, it reports only score distributions/action rates and does not claim FPR or recall.

## Interpretation & Limitations

Report results as controlled-validation or proxy-label agreement, not real-world ground-truth accuracy. Pay special attention to `spa_client` and `privacy_browser` false positives; aggregate FPR can hide those regressions.

### Train/Serve Skew: Whole-Session Training vs Prefix Scoring

- **Offline Training Formulation**: In `ml_pipeline/scripts/data/label_eclog.py`, training vectors are extracted from complete, finished sessions (whole-session aggregation). Terminal statistics (total non-static depth, final behavioral diversity, endpoint concentration, navigation gap across the entire completed session) are collapsed into a single static row per session.
- **Online Serving Formulation**: In production and shadow serving (`RedisTelemetryService.java`), feature vectors are evaluated in real-time as rolling prefix windows computed incrementally at every arriving request once the session depth gate ($N \ge 20$ non-static requests) is satisfied.
- **Operational Implications & Distributional Shift**:
  1. **Early vs. Terminal Trajectories**: At request depth 21 (the initial scoring point), early-session macro-timing variance and navigation gaps reflect initial page loading and exploration, whereas whole-session features capture terminal session stability.
  2. **Feature Drift at Scoring Threshold**: Velocity (`pkts/s`) and diversity metrics on short prefixes (20 requests) exhibit higher variance than the fully stabilized 50-request sliding windows from training.
  3. **Mitigation**: Scoring depth is gated to $N > 20$ non-static requests, and cached evaluation prevents thrashing on rapid intermediate requests; however, model calibration must account for prefix scoring dynamics rather than assuming terminal session properties.

Latency is paired by request/event ID. Paired overhead is `shadow_latency - production_latency`; negative paired overhead indicates measurement or timing effects and must not be interpreted as physical speedup.

Threshold calibration must use a separate validation set. The ECLog holdout must remain untouched.

### Limitations: Deployed Binary Verification
- `app.jar` hash is recorded at run start and end via `docker exec sage-gateway sha256sum /app/app.jar` (verifying run-time container immutability), but is not verified against source code build.
- `main.py` hash is similarly recorded at run start and end via `docker exec sage-ml sha256sum /app/main.py`. Reproducible packaging and container digest pinning remain a follow-up hardening task.

### Archived Runs & Model Attribution

| Run ID / Telemetry Artifact | Shadow Model Used | Fresh Scored Records | Classification & Evidence Status | Notes |
|---|---|---:|---|---|
| `diverse-9a09af81` (`diverse_telemetry_9a09af81.jsonl`) | **timing** (8-feat) | 279 | Timing-model evidence | 140-client campaign; $\max\|\text{logged}-\text{timing}\| = 0.000050$, vs $0.454114$ for weak |
| `diverse-04935d77` (`diverse_telemetry_04935d77.jsonl`) | **timing** (8-feat) | 70 | Timing-model evidence | 35-client smoke test; $\max\|\text{logged}-\text{timing}\| = 0.000048$, vs $0.454114$ for weak |
| `diverse-c109808c` (`diverse_telemetry_c109808c.jsonl`) | **timing** (8-feat) | 4 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000048$ |
| `diverse-29037b60` (`diverse_telemetry_29037b60.jsonl`) | **timing** (8-feat) | 6 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000038$ |
| `diverse-1de5e4da` (`diverse_telemetry_1de5e4da.jsonl`) | **timing** (8-feat) | 4 | Timing-model evidence | Dry run test; $\max\|\text{logged}-\text{timing}\| = 0.000048$ |
| `diverse-e186fd8e` (`diverse_telemetry_e186fd8e.jsonl`) | **weak** (7-feat) | 35 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.454128$ for timing |
| `diverse-5fc1e6d8` (`diverse_telemetry_5fc1e6d8.jsonl`) | **weak** (7-feat) | 35 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.268815$ for timing |
| `diverse-236eb894` (`diverse-236eb894_telemetry.jsonl`) | **weak** (7-feat) | 2 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000039$, vs $0.041570$ for timing |
| `ml_pipeline/data/shadow_telemetry.jsonl` | **weak** (7-feat) | 140 | **Weak-model baseline run; NOT timing evidence** | $\max\|\text{logged}-\text{weak}\| = 0.000049$, vs $0.118477$ for timing |

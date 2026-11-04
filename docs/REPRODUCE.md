# Reproducing the results

Hardware used: one laptop (12 threads, 15 GiB RAM). Times are approximate.

## 0. Environment
```bash
python3 -m venv .venv && .venv/bin/pip install -r ml_pipeline/requirements.txt -r ml_pipeline/requirements-harness.txt pytest==8.3.4
.venv/bin/python -m pytest ml_pipeline/tests -q            # 89 tests
(cd sage-gateway && ./mvnw -o test)                        # 37 tests
```
`requests` is deliberately **not** in `ml_pipeline/requirements.txt`: that file is copied into the inference image, and
changing it invalidates Docker's cached `pip install` layer.

## 1. Data (public, not committed)
EClog (Harvard Dataverse, doi:10.7910/DVN/Z834IK, CC0 with additional terms; downloads are gated by a guestbook):
`eclog_1day.csv` and `eclog.zip` into `ml_pipeline/data/` (`fetch_datasets.py` verifies the MD5). Derived tables are gitignored; rebuild:
```bash
.venv/bin/python ml_pipeline/scripts/train/build_eclog_sessions.py --input ml_pipeline/data/eclog.zip --out ml_pipeline/data/eclog6m_sessions.csv.gz   # ~4 min, sha256 f5cac61f...
.venv/bin/python ml_pipeline/scripts/train/tag_bot_family.py                                                                                            # ~2 min
```

## 2. Axis A (offline) - ~3 min + ~7 min
```bash
.venv/bin/python ml_pipeline/scripts/evaluate/evaluate_eclog6m.py       # results/offline/eclog6m_evaluation.json
.venv/bin/python ml_pipeline/scripts/evaluate/evaluate_markov.py        # results/offline/eclog6m_markov_baseline.json (extracts paths, ~7 min first time)
```
The split (`configs/split_eclog6m_v1.json`) and the frozen v7 models (`ml_pipeline/models/frozen_models_manifest_v7.json`)
are committed; the split reproduces its hash or the scripts abort. Retraining the models is deterministic
(`train_eclog6m_models.py`). The session builder reproduces the committed one-day table exactly
(`results/offline/session_builder_parity_1day.json`).

## 3. Axis B (resolution) - ~3 min
```bash
.venv/bin/python ml_pipeline/scripts/evaluate/evaluate_resolution_sensitivity.py
```
Declared in `configs/offline_protocol_v1_2_resolution.json`; the control run must reproduce the session table or it aborts.

## 4. Stack (axes C and D)
```bash
export SAGE_REDIS_HOST_PORT=6390          # host Redis may own 6379
export SAGE_PROBE_SECRET=$(openssl rand -hex 16)
export EXTRA_SHADOW_MODEL_FILES=eclog6m_prefix_8feature_v1.pkl   # campaign C only
docker compose -f infra/docker-compose.yml up -d --build redis zookeeper kafka ecommerce-shell sage-ml sage-gateway
```
If Kafka exits with `NodeExists`: `docker compose -f infra/docker-compose.yml restart zookeeper`, wait ~20 s, start Kafka again.

## 5. Axis C (overhead) - ~12 min
```bash
.venv/bin/python load-tests/benchmark_gateway_overhead.py --label final
```
A rerun writes a new `bench-final-<id>` directory; the canonical committed run is `bench-final-1971425f`, and the reasons for the superseded runs are in `results/benchmark/README.md`.

## 6. Axis D (campaign C) - ~1 h
Requires a clean git tree (the generator refuses otherwise). Declaration: `configs/campaign_c_declaration_v1.json`
(regenerate with `ml_pipeline/scripts/evaluate/make_campaign_c_declaration.py`).
```bash
.venv/bin/python load-tests/diverse-shadow-traffic.py \
  --frozen-manifest ml_pipeline/models/scoring_manifest_campaign_c_v1.json \
  --campaign-config configs/campaign_c_v1_s1.json --manifest-path /tmp/c1_manifest.json
.venv/bin/python ml_pipeline/scripts/evaluate/archive_campaign_run.py --run-id <RUN_ID> --manifest /tmp/c1_manifest.json --out telemetry/campaign_c
.venv/bin/python ml_pipeline/scripts/evaluate/grade_campaign_c.py --run-id <RUN_ID> \
  --telemetry telemetry/campaign_c/<RUN_ID>/telemetry_<RUN_ID>.jsonl.gz \
  --manifest telemetry/campaign_c/<RUN_ID>/manifest_<RUN_ID>.json --out results/campaign_c/<RUN_ID>
```
Grading the archived run C needs no stack: run the last command with `<RUN_ID>` = `diverse-6a1619a7`.
Runs A and B (archived, checksummed) are re-graded with `ml_pipeline/scripts/evaluate/regrade_campaigns.py`.
Run-to-run variation: the generator's profile seeds are fixed (`profile_seeds` in each config), but timing, scheduling
and ML latency are not, so a new run reproduces the pattern, not the exact counts.

## 7. Integrity
Model hashes are checked before unpickling (inference service and every evaluator). The tag `v2-frozen-models-v6`
pins the original models and evaluator; `v3-campaign-c` pins the build used for campaign C.

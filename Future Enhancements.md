# Future Enhancements

Work that was planned or identified during the JNSM revision but is **not** needed for the current results of record
(`docs/RESULTS.md`) and has **not** been implemented. Nothing here is claimed anywhere in the documentation.

## Evidence and statistics
- **Campaign C replicates (seed sets 2 and 3).** Configs already exist (`configs/campaign_c_v1_s2.json` and `configs/campaign_c_v1_s3.json`). About one hour each; would show run-to-run stability of the live result.
- **Python 3.11 re-run of the final numbers** in the sage-ml image (audit N29); the reported numbers come from Python 3.12.
- **Cross-site (Zanbil) evaluation.** Needs approved access to the restricted Dataverse file; protocol items are in `configs/offline_protocol_v1.json`.
- **Millisecond-resolution training data.** Collect real gateway sessions with ms timestamps and retrain/evaluate, replacing the jitter-based robustness check.
- **Human-verified labels.** A small manually labelled sample of EClog clients to estimate how far the user-agent rule is from true bot status.

## Analyses promised in the plan
- **Table 10 replacement** (feature importance for all 8 features) and **per-client TreeSHAP** for `asset_fetching_bot`, with a timing-feature sweep.
- **Leave-one-profile-out (a)-(d) on campaign C telemetry**, with splits declared before computing.

## Model and deployment
- **Detect `asset_fetching_bot`.** All deployed models score 0 % on it. Candidate: integrate the human-only Isolation Forest (`evaluate_lopo.py`) into the gateway scoring path and evaluate it live.
- **Per-deployment threshold calibration.** The v7 operating points did not transfer to live traffic; calibrate the threshold on in-situ human traffic or use rank-based/percentile thresholds.
- **Re-measure gateway overhead on separate hosts** to separate CPU contention from true added latency (R7 failed at 52.07 ms on one laptop).
- **Enforcement mode.** Remains disabled by design; only shadow evaluation is supported.
- **Sessionisation identity** beyond client IP (`docs/jnsm/SESSION_IDENTITY.md`).

## Reproducibility tooling
- **`run_all` script** that executes every result in `docs/REPRODUCE.md` and a **consistency checker** that compares numbers quoted in the documentation with the result JSON files.
- **Clean-clone test** (fresh clone, rebuild, compare hashes).
- **`TRACEABILITY.md` / `RESULTS_CHANGELOG.md`**: claim-by-claim mapping from manuscript text to result files.
- **Remaining audit items** in `docs/jnsm/STEP_A_AUDIT.md` that are not mentioned in `docs/RESULTS.md` (low-severity findings, not needed for the reported results).
- **Rewrite the README body.** Sections 4-6 still contain the earlier summary (flagged by the revision notice); rewrite them from `docs/RESULTS.md` once the remaining analyses above are decided.

## README inconsistencies still to fix
The README carries a revision notice, but its body predates this revision. Known mismatches with `docs/RESULTS.md`:
1. **Section 4 summary table.** Axis 1 (one-day holdout, 1,202 clients, 95.87 % / 1.21 %) is superseded by the six-month evaluation; Axis 2 (Zanbil) was not reproduced; Axis 3 quotes "60.67 % - 66.67 %" and omits run B (33.33 %) and run C (66.67 %, 450/450 scored); the "Model Selection" row (XGBoost vs random forest, 0.18 ms) was not re-verified.
2. **Section 5 gate text.** "Coverage 97.43 % (341/350)" and "0/200 false positives" describe run A only; run B coverage was 84.86 %, run C is 100 % with 0/300 false positives. The campaign is called "350-client" throughout; run C has 450.
3. **LOPO hybrid claims (sections 5-6).** "`asset_fetching_bot` 0 % -> 100 % (LOPO)" rests on an Isolation Forest that is not part of the deployed gateway and was not re-run; in run C every deployed model scores 0 % on that profile.
4. **Section 6 "Reviewer Remediation (Phases 1-4)"** predates the P0-P4 work (unified evaluator, multi-shadow scoring, six-month models, campaign C) and does not mention it.
5. **Getting started.** Says Python 3.11+ (numbers were produced on 3.12); does not mention `SAGE_REDIS_HOST_PORT`, `SAGE_PROBE_SECRET` (required by the generator) or `EXTRA_SHADOW_MODEL_FILES`.
6. **Section 8 commands.** Steps 3-5 and 7 use the old defaults: the generator now needs a clean git tree, `SAGE_PROBE_SECRET`, and (for campaign C) `--frozen-manifest`/`--campaign-config`; step 4 needs `confluent_kafka`, which is not in `requirements.txt` (the archiver in `docs/REPRODUCE.md` avoids it); step 2 needs the restricted Zanbil file.
7. **Sections 1-3 (architecture, tech stack, feature contract)** were not re-audited in this revision.

## Deferred audit items (`docs/jnsm/STEP_A_AUDIT.md`)
Status from the git history and a spot check of the code; items not listed as closed should be re-triaged before being cited.

**Still open or not addressed**
- **N4** - cart and asset-skip ratios use the Redis hash lifetime (5-minute TTL refreshed per request) rather than the 300 s inactivity sessioniser; only equivalent while gaps stay below 300 s. Add a boundary test or align them.
- **N7** - Kafka send-failure visibility (failures logged at debug level): not re-checked; producer settings (`max.block.ms`, compression, buffer) are present in `application.yaml`.
- **N16** - overlapping RNG streams between profiles (`seed + client_idx`, consecutive profile seeds). Left unchanged so that seed set 1 replays runs A and B; a future seed set could separate the streams.
- **N20** - one /24 per profile (`10.<run>.<profile>.<client>`), so /24 aggregation would merge all clients of a profile; irrelevant while that aggregation is off.
- **N21** - the mock site adds unseeded 5-20 ms response jitter (affects all benchmark modes equally).
- **N23** - Python and Java dependencies are pinned, but the monitoring/UI images in `infra/docker-compose.yml` (Prometheus, Grafana, Kafka UI, RedisInsight) still use `latest`; none is on the scoring path.
- **N24** - `PROD_CONFIDENCE_THRESHOLD` and `SHADOW_CONFIDENCE_THRESHOLD` can override thresholds through the environment, and the prod threshold is not part of the identity check. Campaign runs assert the shadow thresholds; the prod override is unguarded.
- **N27, N28** - Zanbil access and its site-adapted cart/asset rules (blocked on the restricted file).
- **N29** - Python 3.12 host versus 3.11 container (see re-run item above).
- **N3** - parity tests now cover the cart rule and the session loop through the gateway emulator, but there is no cross-language Java-versus-Python test for the *prefix* features beyond the existing golden fixture.

**Believed closed (see `git log`; not independently re-verified here)**
N1 (sensitivity experiment), N2 (six-month data), N5 and N6 (client-keyed Kafka, per-score events), N8 (sync path shadow fields), N9 (atomic decision replace), N10-N15 (unified evaluator definitions; the original evaluator is left unchanged on purpose), N17-N19 (failed clients and workers recorded in the manifest, full Redis clear), N22 (`mvnw` executable), N25 (multi-shadow), N26 (benchmark rewrite).

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

# Archived campaign telemetry (runs A, B and dev run)

Raw Kafka `gateway-telemetry` exports for the evaluated build (`8f79cf6`, tag `v2-frozen-models-v6`).
They were exported by the authors at run time and were not in git. Received 2026-11-01 as
`sage_telemetry_bundle_8881bc1c_ba1a90e8_5fc1e6d8.zip`
(SHA-256 `285a3e8304254677e65963157499c742825aa59d5156152139a7aba39a0abe59`).
Compressed with `gzip -n -9` (deterministic); checksums of the archived files are in `SHA256SUMS`.

| Run | Directory | Raw file (SHA-256 of uncompressed JSONL) | Events | Events with this runId |
|---|---|---|---:|---:|
| A `diverse-8881bc1c` | `diverse-8881bc1c/` | `adversarial_retest_telemetry_8881bc1c.jsonl` (`1921aafd…a478`) | 26,620 | 20,325 |
| B `diverse-ba1a90e8` | `diverse-ba1a90e8/` | `diverse_telemetry_ba1a90e8.jsonl` (`b358acff…bfb0`) | 20,945 | 20,845 |
| dev `diverse-5fc1e6d8` | `diverse-5fc1e6d8/` | `diverse_telemetry_5fc1e6d8.jsonl` (`a8bcbdff…d8ad`) | 1,956 | 1,956 |

Run A's file also holds 6,217 events with runId `unknown` and 78 from `diverse-ab3602da`; run B's
holds 78 from `diverse-a0c63ac4` and 22 `unknown`. They are kept as received; every evaluator filters by runId.

## Provenance checks (all performed 2026-11-01)

- **Run B**: the original evaluator (`evaluate_shadow.py` at `8f79cf6`, SHA-256 `367cff60…fdf8d`, the
  hash recorded in both reports) run on this telemetry and `manifest_ba1a90e8.json` reproduces every
  metric line of the committed `load-tests/diverse_report.md`. The manifest is byte-identical to
  `load-tests/diverse_manifest.json`.
- **Run A**: its manifest was not archived. `manifest_8881bc1c_reconstructed.json` was produced by
  `ml_pipeline/scripts/data/reconstruct_run_manifest.py` (client set from telemetry, profile from the
  client-id naming rule, config from the tag). With it, the original evaluator reproduces every metric
  line of `load-tests/final_campaign_report.md`; only harness/container hashes and profile descriptions
  are missing (they were in the lost manifest).
- **Dev run**: `timing_cascade_analysis.py` on this telemetry reproduces the committed
  `ml_pipeline/reports/timing_cascade_summary.json` exactly.

## Disclosures

- Runs A and B used **different harness code**. Run A: harness SHA-256 `630bdafb…` (= `8f79cf6`).
  Run B: `9643c558…` (= later commit `6f432ba`; uncommitted at run time, report says `DIRTY`). The only
  traffic difference is the third asset path, `/static/logo.png` (A) vs `/images/logo.png` (B); both are
  static under the gateway rule, so logged features are unaffected.
- Run B's report was produced from a dirty working tree (`allow_dirty: true`).

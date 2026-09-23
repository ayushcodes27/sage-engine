# Diverse Shadow Validation Report

Run ID: `diverse-4a2e4b9a`

This is run-specific controlled validation using manifest labels. It is not proof of real-world accuracy, and it must not be reported as production ground truth.
Enforcement remains disabled. Threshold calibration must use a separate validation set; the ECLog holdout remains untouched.

## Profile Matrix

| Profile | Expected class | Asset behavior | Rate |
|---|---|---|---|
| normal_browser | human | Loads most assets | Interactive |
| spa_client | human | Minimal assets, API-heavy | Moderate |
| mobile_browser | human | Loads assets slowly | Slow |
| privacy_browser | human | Selectively skips assets | Interactive |
| slow_scraper | bot | Mostly non-static | Slow |
| asset_fetching_bot | bot | Loads everything | Rapid |
| fast_scraper | bot | Mostly API paths | Very rapid |

Manifest clients: 140
Telemetry events matched by run_id: 12089
Telemetry events joined to manifest client_id: 12089
Telemetry events without manifest truth: 0
Manifest clients without telemetry: 0
Events with missing event/model metadata: 0
Duplicate event IDs in matched telemetry: 0
Shadow-scored events: 0
Shadow-scored clients: 0
Clients without a valid shadow score: 140

No valid shadow predictions matched the truth manifest. Metrics are unavailable; infrastructure failures must not be counted as bot misses.
shadow_action
None    12089

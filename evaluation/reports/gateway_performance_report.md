# Gateway Performance Report

This full-combat evaluation was run against the protected SAGE Gateway endpoint with all active traffic profiles enabled. Locust measured end-to-end gateway response time while the system enforced bot mitigation rules under attack-heavy load.

| Scenario | Users | Duration | Total Requests | Throughput | Median Latency | p99 Latency | Failure/Block Count |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full Combat | 140 | 10m | 314,278 | 524.37 req/s | 7 ms | 62 ms | 311,000 |

Human traffic remained clean during this run, with 692 human requests and 0 failures.

## Playwright Human False Positive Evaluation

This browser-driven evaluation was run against the protected SAGE Gateway endpoint using Playwright human browsing sessions. Each journey reused a stable human IP and continued until it crossed the gateway's post-grace evaluation threshold.

| Scenario | Journeys | Min Requests/Journey | Concurrency | Gateway Requests | Blocked Journeys | Blocked Requests | Journey FPR | Request FPR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Playwright Human FPR | 50 | 22 | 5 | 1,100 | 0 | 0 | 0.00% | 0.00% |

All 50 Playwright journeys crossed the configured request threshold, and no human journey received a gateway block.

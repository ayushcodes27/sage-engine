# Session identity in the evaluated and remediated gateway

**Decision:** all session state stays keyed by client IP (the `X-Forwarded-For` first hop). The `__sage_sid`
cookie and the /24 subnet counter added in `2d063bd` remain **unused** for campaign C. This keeps campaign C
comparable with runs A/B, which were keyed by IP.

## What exists in code
| Mechanism | Written | Read |
|---|---|---|
| `__sage_sid` cookie | `FastPathFilter` sets request attribute `SAGE-Session-Id` (new UUID if absent); `GatewayController.withSessionCookie` sets `Set-Cookie` | nowhere |
| /24 counter `sage:subnet:hits:<a.b.c>.0/24` | `RedisTelemetryService.incrementSubnetCounter` on every request | nowhere (return value discarded) |
| Session state (`sage:timestamps:`, `sage:paths:`, `sage:telemetry:`, `sage:first_seen:`, `sage:reqcount:`, `sage:ml-decision:`) | keyed by `ip` | keyed by `ip` |

## Why they are not wired in for campaign C
- **/24 aggregation would merge clients.** The generator assigns `10.<run>.<profile>.<client>`, so every client of a
  profile shares one /24. Aggregating by /24 would turn 50–75 clients into one session per profile.
- **Cookie identity changes the unit of analysis.** `requests.Session` stores and returns cookies, so clients would
  be keyed by cookie instead of IP; with the same generator this is equivalent in the benign case but differs from
  runs A/B as soon as a cookie is dropped or rotated, which is precisely the evasion case a cookie key invites.

## Claims that must not be made from this code
- That SAGE tracks sessions by cookie, or detects distributed (/24) scrapers.
- Both are limitations to state; each needs its own declared experiment (adversarial profiles that rotate IPs
  within a /24 or drop cookies) before any claim.

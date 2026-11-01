"""
Offline emulation of the gateway's per-request feature state (RedisTelemetryService) and scoring gate
(MLInferenceFilter), used to build prefix-trained rows (B3).

Per client session (inactivity gap > 300 s starts a new session, the Redis 5-min TTL refreshed on every
request), for every request in time order the gateway:
  - counts total/cart/static hits over the whole session (Redis hash lifetime),
  - pushes non-static requests into a 50-entry window (f0 = window size, capped),
  - measures duration from the session's first request of any kind (first-seen key),
and scores when f0 > 20 and duration >= 3 s. Feature definitions are the shared ones in label_eclog.py
(path canonicalisation, static and cart rules) and match the Java methods one-for-one; the golden fixture
test in ml_pipeline/tests/test_gateway_emulator.py checks that.
"""

from collections import Counter, deque
import math

from label_eclog import extract_path, is_cart_uri, is_static_asset

WINDOW_SIZE = 50
SESSION_GAP_S = 300.0
DEPTH_THRESHOLD = 20      # MLInferenceFilter.SESSION_DEPTH_THRESHOLD: score when f0 > 20
MIN_DURATION_S = 3.0

FEATURES = [
    "SAGE_Session_Depth", "SAGE_Temporal_Variance", "SAGE_Request_Velocity", "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration", "SAGE_Cart_Ratio", "SAGE_Asset_Skip_Ratio",
    "SAGE_NonStatic_Navigation_Gap", "SAGE_NonStatic_Long_Gap_Ratio",
]


def window_features(times_s, paths, total_hits, cart_hits, static_hits):
    """Features from the non-static window (oldest first) and session counters, as in RedisTelemetryService."""
    n = len(times_s)
    out = {"SAGE_Session_Depth": float(n)}
    if n >= 2:
        span = max(times_s[-1] - times_s[0], 0.001)
        gaps = [b - a for a, b in zip(times_s, times_s[1:])]
        mean = sum(gaps) / len(gaps)
        if mean == 0:
            tv = 0.0
        else:
            tv = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) / mean
        s = sorted(gaps)
        m = len(s) // 2
        out.update({
            "SAGE_Request_Velocity": n / span,
            "SAGE_Temporal_Variance": tv,
            "SAGE_NonStatic_Navigation_Gap": s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0,
            "SAGE_NonStatic_Long_Gap_Ratio": sum(1 for g in gaps if g >= 0.50) / len(gaps),
        })
        counts = Counter(paths)
        out["SAGE_Behavioral_Diversity"] = -sum((c / n) * math.log(c / n) for c in counts.values())
    else:
        out.update({"SAGE_Request_Velocity": 1.0, "SAGE_Temporal_Variance": 0.0, "SAGE_Behavioral_Diversity": 0.0,
                    "SAGE_NonStatic_Navigation_Gap": 0.0, "SAGE_NonStatic_Long_Gap_Ratio": 0.0})
    out["SAGE_Endpoint_Concentration"] = (max(Counter(paths).values()) / n) if n else 0.0
    out["SAGE_Cart_Ratio"] = cart_hits / total_hits if total_hits else 0.0
    out["SAGE_Asset_Skip_Ratio"] = 1.0 - static_hits / total_hits if total_hits else 1.0
    return out


def iter_session_states(times_s, raw_uris):
    """Yield (request_index, non_static_count, duration_s, features) after every request of ONE session.

    features is a zero-argument callable over the live window; call it before advancing the iterator.
    """
    win_t, win_p = deque(maxlen=WINDOW_SIZE), deque(maxlen=WINDOW_SIZE)
    c = {"total": 0, "cart": 0, "static": 0}
    ns_count = 0
    first = times_s[0] if len(times_s) else None

    def features():
        return window_features(list(win_t), list(win_p), c["total"], c["cart"], c["static"])

    for i, (t, uri) in enumerate(zip(times_s, raw_uris)):
        p = extract_path(uri)
        st = is_static_asset(p)
        c["total"] += 1
        c["cart"] += bool(is_cart_uri(p))
        c["static"] += bool(st)
        if not st:
            win_t.append(t)
            win_p.append(p)
            ns_count += 1
        yield i, ns_count, t - first, features


def first_score(times_s, raw_uris):
    """(request_index, non_static_count, duration_s, features) at the gateway's first scoring point, or None.

    The gate is f0 > 20 and duration >= 3 s; f0 = min(non_static_count, 50), so f0 > 20 iff count > 20.
    """
    for i, ns, dur, features in iter_session_states(times_s, raw_uris):
        if ns > DEPTH_THRESHOLD and dur >= MIN_DURATION_S:
            return i, ns, dur, features()
    return None


def sessionize(times_s):
    """Session index per request for one client's time-sorted requests (gap > 300 s starts a new session)."""
    idx, out, prev = 0, [], None
    for t in times_s:
        if prev is not None and t - prev > SESSION_GAP_S:
            idx += 1
        out.append(idx)
        prev = t
    return out

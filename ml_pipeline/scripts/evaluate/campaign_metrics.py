"""
campaign_metrics.py

One definition of client-level metrics and of the unified / revised gates, applied identically
to every campaign run (A, B and later runs). The ORIGINAL G1–G7 are not re-implemented here:
regrade_campaigns.py runs the tag-pinned original evaluator for those.

Client rule: a client is predicted bot if any scored decision for that client is flagged.
Every manifest client is counted: an unscored bot is a miss, an unscored human is a negative.
Scorable: the client's telemetry reaches non-static session depth > 20 (sessionDepth is logged on
every event; session duration is not logged, so it cannot be part of a telemetry-only definition).
"""

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from scipy.stats import beta

BOT_PROFILES = ["slow_scraper", "asset_fetching_bot", "fast_scraper"]
HUMAN_PROFILES = ["normal_browser", "spa_client", "mobile_browser", "privacy_browser"]
PROFILE_ORDER = HUMAN_PROFILES + BOT_PROFILES
DEPTH_GATE = 20.0
FAILURE_STATUSES = {"Timeout", "SemaphoreFull", "Error", "Failed"}
SHADOW_IDENTITY_FIELDS = [
    "prodModelSha256",
    "shadowModelSha256",
    "shadowContractHash",
    "shadowFeatureListHash",
    "shadowThreshold",
]


# ── statistics ────────────────────────────────────────────────────────────────

def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> Dict[str, Optional[float]]:
    """Exact binomial interval: point, two-sided (1-alpha) bounds and one-sided (1-alpha) upper bound."""
    if n <= 0:
        return {"k": k, "n": n, "point": None, "lower": None, "upper": None, "upper_one_sided": None}
    lower = 0.0 if k == 0 else float(beta.ppf(alpha / 2.0, k, n - k + 1))
    upper = 1.0 if k == n else float(beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))
    upper_one = 1.0 if k == n else float(beta.ppf(1.0 - alpha, k + 1, n - k))
    return {"k": k, "n": n, "point": k / n, "lower": lower, "upper": upper, "upper_one_sided": upper_one}


# ── telemetry ─────────────────────────────────────────────────────────────────

def _open(path):
    path = str(path)
    return gzip.open(path, "rt", encoding="utf-8-sig") if path.endswith(".gz") else open(path, encoding="utf-8-sig")


def load_events(path, run_id: str) -> List[dict]:
    """Request events of one run, sorted per client by gateway timestamp (Kafka order is not per-client)."""
    events = []
    with _open(path) as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("runId") == run_id:
                events.append(e)
    events.sort(key=lambda e: (e.get("userId") or "", e.get("timestamp") or 0))
    return events


def ml(e) -> dict:
    return e.get("mlMetadata") or {}


def shadow_scored(e) -> bool:
    m = ml(e)
    return m.get("shadowStatus") == "ok" and m.get("shadowBotProbability") is not None and m.get("shadowIsBotFlag") is not None


def shadow_flagged(e) -> bool:
    return shadow_scored(e) and ml(e).get("shadowIsBotFlag") == 1


def prod_scored(e) -> bool:
    m = ml(e)
    return m.get("evaluationStatus") in ("Scored", "Cached") and m.get("botProbability") is not None


def prod_flagged(e) -> bool:
    return prod_scored(e) and ml(e).get("isBotFlag") == 1


MODELS = {
    "shadow_eclog_timing_8feat": (shadow_scored, shadow_flagged),
    "prod_sage_binary_7feat": (prod_scored, prod_flagged),
}


# ── client table ──────────────────────────────────────────────────────────────

def _depths(evs):
    return [float((e.get("features") or {}).get("sessionDepth") or 0.0) for e in evs]


def unscored_reason(evs: List[dict]) -> str:
    if not evs:
        return "no_telemetry"
    depths = _depths(evs)
    if max(depths) <= DEPTH_GATE:
        reset = any(b < a for a, b in zip(depths, depths[1:]))
        return "never_reached_depth_21_after_session_reset" if reset else "never_reached_depth_21"
    statuses = Counter(ml(e).get("evaluationStatus") for e in evs if (e.get("features") or {}).get("sessionDepth", 0) > DEPTH_GATE)
    if any(s in FAILURE_STATUSES for s in statuses):
        return "ml_failure_after_depth_21"
    return "depth_21_reached_but_gate_not_met"


def client_table(events: Iterable[dict], clients: Dict[str, dict], model: str) -> List[dict]:
    scored_fn, flagged_fn = MODELS[model]
    by_client: Dict[str, List[dict]] = {}
    for e in events:
        by_client.setdefault(e.get("userId"), []).append(e)

    rows = []
    for cid, meta in sorted(clients.items()):
        evs = by_client.get(cid, [])
        depths = _depths(evs)
        scored = [e for e in evs if scored_fn(e)]
        rows.append({
            "client_id": cid,
            "profile": meta["profile"],
            "true_class": meta["true_class"],
            "events": len(evs),
            "max_depth": max(depths) if depths else 0.0,
            "scorable": bool(depths) and max(depths) > DEPTH_GATE,
            "scored": bool(scored),
            "scored_events": len(scored),
            "flagged": any(flagged_fn(e) for e in scored),
            "unscored_reason": None if scored else unscored_reason(evs),
        })
    return rows


# ── metrics ───────────────────────────────────────────────────────────────────

def model_metrics(rows: List[dict]) -> dict:
    bots = [r for r in rows if r["true_class"] == "bot"]
    humans = [r for r in rows if r["true_class"] == "human"]
    tp = sum(r["flagged"] for r in bots)
    fp = sum(r["flagged"] for r in humans)
    fn, tn = len(bots) - tp, len(humans) - fp

    per_profile = {}
    for p in PROFILE_ORDER:
        pr = [r for r in rows if r["profile"] == p]
        if not pr:
            continue
        cls = pr[0]["true_class"]
        flagged = sum(r["flagged"] for r in pr)
        scored = [r for r in pr if r["scored"]]
        per_profile[p] = {
            "true_class": cls,
            "clients": len(pr),
            "scored_clients": len(scored),
            "flagged": flagged,
            "metric": "recall" if cls == "bot" else "fpr",
            "all_clients": clopper_pearson(flagged, len(pr)),
            "scored_only": clopper_pearson(sum(r["flagged"] for r in scored), len(scored)),
            "unscored_reasons": dict(Counter(r["unscored_reason"] for r in pr if not r["scored"])),
        }

    bot_recalls = {p: per_profile[p]["all_clients"]["point"] for p in BOT_PROFILES if p in per_profile}
    return {
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "bot_recall": clopper_pearson(tp, tp + fn),
        "human_fpr": clopper_pearson(fp, fp + tn),
        "precision": clopper_pearson(tp, tp + fp),
        "macro_bot_recall": sum(bot_recalls.values()) / len(BOT_PROFILES) if bot_recalls else None,
        "per_profile": per_profile,
        "scored_clients": sum(r["scored"] for r in rows),
        "scorable_clients": sum(r["scorable"] for r in rows),
        "scorable_and_scored_clients": sum(r["scorable"] and r["scored"] for r in rows),
    }


# ── revised gates (configs/gates_revised_v1.json) ─────────────────────────────

def failure_records(events: Iterable[dict]) -> int:
    n = 0
    for e in events:
        m = ml(e)
        status = (e.get("response") or {}).get("status") or 0
        if m.get("evaluationStatus") in FAILURE_STATUSES or m.get("shadowStatus") in ("timeout", "error") or status >= 500:
            n += 1
    return n


def identity_check(events: Iterable[dict], expected: dict) -> dict:
    tuples = Counter()
    missing = 0
    for e in events:
        if not shadow_scored(e):
            continue
        m = ml(e)
        t = tuple(m.get(f) for f in SHADOW_IDENTITY_FIELDS)
        if any(v is None for v in t):
            missing += 1
        else:
            tuples[t] += 1
    want = (
        expected.get("prod_model_sha256"),
        expected.get("shadow_model_sha256"),
        expected.get("shadow_contract_hash"),
        expected.get("shadow_feature_list_hash"),
        float(expected.get("shadow_threshold")) if expected.get("shadow_threshold") is not None else None,
    )
    match = len(tuples) == 1 and missing == 0 and _tuple_eq(next(iter(tuples)), want)
    return {"distinct_tuples": len(tuples), "records_missing_identity": missing, "matches_manifest": match}


def _tuple_eq(obs, want):
    *oh, ot = obs
    *wh, wt = want
    return list(oh) == list(wh) and ot is not None and wt is not None and abs(float(ot) - float(wt)) <= 1e-9


def timing_features_active(events: Iterable[dict]) -> bool:
    for e in events:
        if shadow_scored(e):
            f = e.get("features") or {}
            if (f.get("nonStaticNavigationGap") or 0) > 0 or (f.get("nonStaticLongGapRatio") or 0) > 0:
                return True
    return False


def revised_gates(gate_cfg: dict, metrics: dict, events: List[dict], expected_identity: dict,
                  gateway_overhead_p95_ms: Optional[float]) -> Dict[str, dict]:
    g = gate_cfg["gates"]
    ident = identity_check(events, expected_identity)
    fails = failure_records(events)
    scorable = metrics["scorable_clients"]
    coverage = metrics["scorable_and_scored_clients"] / scorable if scorable else None
    fpr = metrics["human_fpr"]
    per_bot = {p: metrics["per_profile"][p]["all_clients"]["point"] for p in BOT_PROFILES if p in metrics["per_profile"]}
    macro = metrics["macro_bot_recall"]
    r6 = g["R6_bot_recall"]

    out = {
        "R1_identity": {"observed": ident, "pass": ident["matches_manifest"]},
        "R2_coverage": {"observed": coverage, "threshold": g["R2_coverage"]["min"],
                        "pass": coverage is not None and coverage >= g["R2_coverage"]["min"]},
        "R3_timeouts_errors": {"observed": fails, "threshold": g["R3_timeouts_errors"]["max"],
                               "pass": fails <= g["R3_timeouts_errors"]["max"]},
        "R4_timing_features": {"observed": timing_features_active(events), "pass": timing_features_active(events)},
        "R5_human_fpr": {"observed": fpr, "threshold": g["R5_human_fpr"]["upper_bound_max"],
                         "pass": fpr["upper_one_sided"] is not None and fpr["upper_one_sided"] <= g["R5_human_fpr"]["upper_bound_max"]},
        "R6_bot_recall": {"observed": {"macro": macro, "per_profile": per_bot},
                          "threshold": {"macro_min": r6["macro_min"], "per_profile_min": r6["per_profile_min"]},
                          "pass": macro is not None and macro >= r6["macro_min"]
                          and len(per_bot) == len(r6["bot_profiles"])
                          and all(v >= r6["per_profile_min"] for v in per_bot.values())},
        "R7_gateway_overhead": {"observed": gateway_overhead_p95_ms,
                                "threshold": g["R7_gateway_overhead"]["max_p95_overhead_ms"],
                                "pass": gateway_overhead_p95_ms is not None
                                and gateway_overhead_p95_ms < g["R7_gateway_overhead"]["max_p95_overhead_ms"],
                                "note": None if gateway_overhead_p95_ms is not None else "not measured -> FAIL"},
    }
    return out


def load_gate_config(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

"""
Regression tests for campaign_metrics.py. Each test names the audit defect it would have caught
(docs/jnsm/STEP_A_AUDIT.md).
"""

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "evaluate"))
import campaign_metrics as cm  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GATES = cm.load_gate_config(REPO / "configs" / "gates_revised_v1.json")
IDENTITY = {
    "prod_model_sha256": "p", "shadow_model_sha256": "s", "shadow_contract_hash": "c",
    "shadow_feature_list_hash": "f", "shadow_threshold": 0.35,
}


def ev(cid, ts, depth, scored=False, flagged=False, status="Skipped", prod_flag=0, gap=0.8, run="r"):
    ml = {"evaluationStatus": status, "shadowStatus": "ok" if scored else "skipped"}
    if scored:
        ml.update({"shadowBotProbability": 0.9 if flagged else 0.1, "shadowIsBotFlag": int(flagged),
                   "botProbability": 0.9 if prod_flag else 0.1, "isBotFlag": prod_flag,
                   "prodModelSha256": "p", "shadowModelSha256": "s", "shadowContractHash": "c",
                   "shadowFeatureListHash": "f", "shadowThreshold": 0.35})
        ml["evaluationStatus"] = "Scored"
    return {"runId": run, "userId": cid, "timestamp": ts, "response": {"status": 200},
            "features": {"sessionDepth": depth, "nonStaticNavigationGap": gap, "nonStaticLongGapRatio": 0.5},
            "mlMetadata": ml}


def scored_client(cid, flagged):
    return [ev(cid, i, float(i + 1)) for i in range(21)] + [ev(cid, 21, 22.0, scored=True, flagged=flagged)]


def clients(spec):
    return {cid: {"profile": cid.rsplit("-", 1)[0], "true_class": cls} for cid, cls in spec.items()}


def test_clopper_pearson_known_values():
    ci = cm.clopper_pearson(0, 200)
    assert ci["upper"] == pytest.approx(0.0182753, abs=1e-6)
    assert ci["upper_one_sided"] == pytest.approx(1 - 0.05 ** (1 / 200), abs=1e-9)
    assert cm.clopper_pearson(0, 300)["upper_one_sided"] < 0.01 < cm.clopper_pearson(0, 300)["upper"]


def test_unscored_bot_counts_as_miss():
    """Defect 9: run A fast_scraper recall was computed over scored clients only."""
    events = scored_client("fast_scraper-00", True) + [ev("fast_scraper-01", i, min(50.0, i + 1.0)) for i in range(60)]
    rows = cm.client_table(events, clients({"fast_scraper-00": "bot", "fast_scraper-01": "bot"}), "shadow_eclog_timing_8feat")
    pp = cm.model_metrics(rows)["per_profile"]["fast_scraper"]
    assert pp["all_clients"]["point"] == 0.5
    assert pp["scored_only"]["point"] == 1.0
    assert pp["unscored_reasons"] == {"depth_21_reached_but_gate_not_met": 1}


def _metrics_for(recalls):
    events, spec = [], {}
    for p, flagged in recalls.items():
        for i, f in enumerate(flagged):
            cid = f"{p}-{i:02d}"
            spec[cid] = "bot"
            events += scored_client(cid, f)
    for i in range(3):
        cid = f"normal_browser-{i:02d}"
        spec[cid] = "human"
        events += scored_client(cid, False)
    return events, cm.model_metrics(cm.client_table(events, clients(spec), "shadow_eclog_timing_8feat"))


def test_per_profile_minimum_recall_gate_is_evaluated():
    """Defect 1: the per-profile gate was guarded by an undefined name and always passed."""
    events, m = _metrics_for({"slow_scraper": [True] * 4, "asset_fetching_bot": [False] * 4, "fast_scraper": [True] * 4})
    r6 = cm.revised_gates(GATES, m, events, IDENTITY, 10.0)["R6_bot_recall"]
    assert r6["observed"]["per_profile"]["asset_fetching_bot"] == 0.0
    assert r6["pass"] is False


def test_fpr_gate_uses_upper_bound():
    """Defect 10: G5 was gated on the point estimate; 0/3 humans must not pass a 1% bound."""
    events, m = _metrics_for({"slow_scraper": [True], "asset_fetching_bot": [True], "fast_scraper": [True]})
    r5 = cm.revised_gates(GATES, m, events, IDENTITY, 10.0)["R5_human_fpr"]
    assert m["human_fpr"]["point"] == 0.0
    assert r5["pass"] is False


def test_overhead_gate_fails_without_measurement():
    """N10: G7 passed vacuously when no latency was logged."""
    events, m = _metrics_for({"slow_scraper": [True], "asset_fetching_bot": [True], "fast_scraper": [True]})
    assert cm.revised_gates(GATES, m, events, IDENTITY, None)["R7_gateway_overhead"]["pass"] is False
    assert cm.revised_gates(GATES, m, events, IDENTITY, 12.0)["R7_gateway_overhead"]["pass"] is True


def test_gateway_timeouts_count_as_failures():
    """N11: gateway Timeout/SemaphoreFull lived only in evaluationStatus and was ignored by G3."""
    events = [ev("x-00", 1, 22.0, status="Timeout"), ev("x-00", 2, 23.0, status="SemaphoreFull"), ev("x-00", 3, 24.0)]
    assert cm.failure_records(events) == 2


def test_identity_mismatch_fails():
    events = scored_client("slow_scraper-00", True)
    assert cm.identity_check(events, IDENTITY)["matches_manifest"] is True
    assert cm.identity_check(events, dict(IDENTITY, shadow_model_sha256="other"))["matches_manifest"] is False


def test_session_reset_reason():
    """Defect 14: Redis expiry mid-session restarted depth; the client never reached depth 21."""
    events = [ev("mobile_browser-00", i, float(i % 12 + 1)) for i in range(30)]
    rows = cm.client_table(events, clients({"mobile_browser-00": "human"}), "shadow_eclog_timing_8feat")
    assert rows[0]["unscored_reason"] == "never_reached_depth_21_after_session_reset"


def test_load_events_orders_by_client_timestamp(tmp_path):
    """N5: Kafka export order is not per-client time order."""
    p = tmp_path / "t.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for e in [ev("a-00", 30, 3.0), ev("a-00", 10, 1.0), ev("b-00", 5, 1.0, run="other"), ev("a-00", 20, 2.0)]:
            f.write(json.dumps(e) + "\n")
    out = cm.load_events(p, "r")
    assert [e["timestamp"] for e in out] == [10, 20, 30]

"""
The offline gateway emulator (prefix rows, B3) must reproduce the shared golden fixture that the Java
CrossLanguageParityTest also checks, and must apply the gateway's scoring gate (f0 > 20, duration >= 3 s).
"""

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "scripts" / "train"))
from gateway_emulator import FEATURES, first_score, iter_session_states, sessionize  # noqa: E402

FIXTURE = BASE_DIR / "ml_pipeline" / "models" / "fixtures" / "feature_parity_golden.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


def emulate(requests, eval_at):
    reqs = requests[:eval_at]
    times = [r["timestamp_ms"] / 1000.0 for r in reqs]
    uris = [r.get("raw_path", r["path"]) for r in reqs]
    sess = sessionize(times)
    last = [i for i, s in enumerate(sess) if s == sess[-1]]
    states = list((i, f()) for i, _, _, f in iter_session_states([times[i] for i in last], [uris[i] for i in last]))
    return states[-1][1]


@pytest.mark.parametrize("case", [c for c in CASES if c["eval_at_request"] > 0], ids=lambda c: c["case_id"])
def test_matches_golden_fixture(case):
    got = emulate(case["requests"], case["eval_at_request"])
    for name, expected in case["expected_features"].items():
        assert got[name] == pytest.approx(expected, abs=1e-5), name
    assert set(case["expected_features"]) <= set(FEATURES)


def _session(n_nonstatic, gap_s, static_every=0):
    times, uris, t = [], [], 0.0
    for i in range(n_nonstatic):
        times.append(t)
        uris.append(f"/p/{i % 7}")
        if static_every and i % static_every == 0:
            times.append(t)
            uris.append("/static/a.css")
        t += gap_s
    return times, uris


def test_first_score_at_k21_when_duration_met():
    i, ns, dur, f = first_score(*_session(40, 1.0))
    assert ns == 21 and f["SAGE_Session_Depth"] == 21.0 and dur == pytest.approx(20.0)


def test_first_score_waits_for_duration_gate():
    # 0.1 s gaps: request 21 is at 2.0 s, the gate opens at the request reaching 3.0 s (count 31)
    i, ns, dur, f = first_score(*_session(60, 0.1))
    assert ns == 31 and dur >= 3.0 and f["SAGE_Session_Depth"] == 31.0


def test_depth_is_capped_window_size():
    i, ns, dur, f = first_score(*_session(400, 0.01))  # gate opens at 3 s = count 301
    assert ns > 50 and f["SAGE_Session_Depth"] == 50.0


def test_static_requests_count_for_duration_not_depth():
    times, uris = _session(21, 0.1, static_every=1)
    times.append(5.0)
    uris.append("/static/late.js")  # static request opens the duration gate at depth 21
    i, ns, dur, f = first_score(times, uris)
    assert i == len(times) - 1 and ns == 21 and f["SAGE_Session_Depth"] == 21.0


def test_never_scored_below_depth():
    assert first_score(*_session(21 - 1, 1.0)) is None


def test_sessionize_gap_boundary():
    assert sessionize([0.0, 300.0, 600.1]) == [0, 0, 1]

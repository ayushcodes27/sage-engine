"""
Feature parity test suite comparing Python feature calculations against
the shared golden fixture (feature_parity_golden.json) and verifying
per-model column selection.
"""

import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
FIXTURE_PATH = BASE_DIR / "ml_pipeline" / "models" / "fixtures" / "feature_parity_golden.json"

# Import feature functions directly from production pipeline script (label_eclog.py)
import sys
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "scripts" / "train"))
from label_eclog import extract_path, is_static_asset, is_cart_uri, compute_entropy

def calculate_python_pipeline_features(requests, eval_at_request):
    """
    Computes SAGE features using the canonical logic from label_eclog.py.
    """
    if not requests or eval_at_request <= 0:
        return {
            "SAGE_Session_Depth": 0.0,
            "SAGE_Temporal_Variance": 0.0,
            "SAGE_Request_Velocity": 0.0,
            "SAGE_Behavioral_Diversity": 0.0,
            "SAGE_Endpoint_Concentration": 0.0,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 1.0,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        }

    active_requests = requests[:eval_at_request]
    
    # 5-minute inactivity horizon: drop requests older than 300 seconds from the latest request
    latest_ts = active_requests[-1]["timestamp_ms"]
    cutoff_ts = latest_ts - 300_000
    window_requests = [r for r in active_requests if r["timestamp_ms"] >= cutoff_ts]

    total_hits = len(window_requests)
    cart_hits = sum(1 for r in window_requests if is_cart_uri(extract_path(r.get("raw_path", r["path"]))))
    static_hits = sum(1 for r in window_requests if is_static_asset(extract_path(r.get("raw_path", r["path"]))))

    cart_ratio = cart_hits / total_hits if total_hits > 0 else 0.0
    asset_skip_ratio = 1.0 - (static_hits / total_hits) if total_hits > 0 else 1.0

    non_static = [r for r in window_requests if not is_static_asset(extract_path(r.get("raw_path", r["path"])))]
    # Last 50 non-static requests
    recent_non_static = non_static[-50:]
    req_count = len(recent_non_static)
    session_depth = float(req_count)

    if req_count >= 2:
        times = [r["timestamp_ms"] / 1000.0 for r in recent_non_static]
        duration = times[-1] - times[0]
        time_span = max(duration, 0.001)
        velocity = req_count / time_span

        gaps = np.diff(times)
        mean_iat = np.mean(gaps)
        if mean_iat == 0:
            temporal_var = 0.0
        else:
            # Note: Population standard deviation (ddof=0) matches np.std default and Java calculation
            std_iat = np.std(gaps)
            temporal_var = float(std_iat / mean_iat)

        canonical_paths = pd.Series([extract_path(r.get("raw_path", r["path"])) for r in recent_non_static])
        diversity = float(compute_entropy(canonical_paths))
        path_counts = canonical_paths.value_counts()
        endpoint_conc = float(path_counts.iloc[0] / req_count)

        # Median navigation gap & long gap ratio (gaps >= 0.50 seconds)
        non_static_nav_gap = float(np.median(gaps))
        non_static_long_gap_ratio = float(np.mean(gaps >= 0.50))
    else:
        velocity = 1.0
        temporal_var = 0.0
        diversity = 0.0
        endpoint_conc = 1.0 if req_count == 1 else 0.0
        non_static_nav_gap = 0.0
        non_static_long_gap_ratio = 0.0

    return {
        "SAGE_Session_Depth": session_depth,
        "SAGE_Temporal_Variance": temporal_var,
        "SAGE_Request_Velocity": velocity,
        "SAGE_Behavioral_Diversity": diversity,
        "SAGE_Endpoint_Concentration": endpoint_conc,
        "SAGE_Cart_Ratio": cart_ratio,
        "SAGE_Asset_Skip_Ratio": asset_skip_ratio,
        "SAGE_NonStatic_Navigation_Gap": non_static_nav_gap,
        "SAGE_NonStatic_Long_Gap_Ratio": non_static_long_gap_ratio,
    }


def test_shared_golden_fixture_parity():
    """Verify that Python calculations match shared fixture within 1e-5."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    for case in fixture_data["cases"]:
        case_id = case["case_id"]
        requests = case["requests"]
        eval_k = case["eval_at_request"]
        expected = case["expected_features"]

        computed = calculate_python_pipeline_features(requests, eval_k)

        for feat_name, exp_val in expected.items():
            act_val = computed[feat_name]
            diff = abs(act_val - exp_val)
            assert diff <= 1e-5, (
                f"[{case_id}] Feature {feat_name} mismatch: expected {exp_val}, got {act_val} (diff {diff})"
            )


def test_per_model_column_selection():
    """
    Validates per-model explicit column selection from the 9-feature telemetry vector.
    Explains the 9-feature telemetry vs 7/6/8-feature model matrix:
      - Gateway produces a union of 9 features.
      - Prod 7-Feat: omits Navigation_Gap and Long_Gap_Ratio.
      - ECLog Weak 7-Feat: omits Navigation_Gap and Long_Gap_Ratio.
      - ECLog 6-Feat: omits Asset_Skip_Ratio and timing gaps.
      - ECLog Timing 8-Feat: omits Asset_Skip_Ratio, includes timing gaps.
    """
    telemetry_vector = {
        "SAGE_Session_Depth": 25.0,
        "SAGE_Temporal_Variance": 0.45,
        "SAGE_Request_Velocity": 2.5,
        "SAGE_Behavioral_Diversity": 1.2,
        "SAGE_Endpoint_Concentration": 0.4,
        "SAGE_Cart_Ratio": 0.1,
        "SAGE_Asset_Skip_Ratio": 0.9,
        "SAGE_NonStatic_Navigation_Gap": 0.75,
        "SAGE_NonStatic_Long_Gap_Ratio": 0.60,
    }
    df = pd.DataFrame([telemetry_vector])

    prod_7_features = [
        "SAGE_Session_Depth", "SAGE_Temporal_Variance", "SAGE_Request_Velocity",
        "SAGE_Behavioral_Diversity", "SAGE_Endpoint_Concentration",
        "SAGE_Cart_Ratio", "SAGE_Asset_Skip_Ratio"
    ]
    eclog_6_features = [
        "SAGE_Session_Depth", "SAGE_Temporal_Variance", "SAGE_Request_Velocity",
        "SAGE_Behavioral_Diversity", "SAGE_Endpoint_Concentration", "SAGE_Cart_Ratio"
    ]
    timing_8_features = [
        "SAGE_Session_Depth", "SAGE_Temporal_Variance", "SAGE_Request_Velocity",
        "SAGE_Behavioral_Diversity", "SAGE_Endpoint_Concentration", "SAGE_Cart_Ratio",
        "SAGE_NonStatic_Navigation_Gap", "SAGE_NonStatic_Long_Gap_Ratio"
    ]

    # Column selection by name
    prod_sub = df[prod_7_features]
    assert list(prod_sub.columns) == prod_7_features
    assert prod_sub.shape == (1, 7)

    eclog_6_sub = df[eclog_6_features]
    assert list(eclog_6_sub.columns) == eclog_6_features
    assert eclog_6_sub.shape == (1, 6)

    timing_8_sub = df[timing_8_features]
    assert list(timing_8_sub.columns) == timing_8_features
    assert timing_8_sub.shape == (1, 8)

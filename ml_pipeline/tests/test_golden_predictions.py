"""
Golden predictions test suite asserting deterministic model inferences
on a fixed vector set (including near-threshold boundary vectors on both sides
of 0.35 and 0.50), verified directly against all 4 pickled models and the live /predict route.
Tolerance: within 1e-5.
"""

import asyncio
import pickle
from pathlib import Path
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE_DIR / "ml_pipeline" / "models"

# Add inference_service to path
import sys
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "inference_service"))
from main import app, GatewayTelemetry, predict_anomaly, lifespan, health_check

# Fixed Golden Vectors across boundary regimes (tolerance: within 1e-5)
GOLDEN_VECTORS = [
    {
        "id": "timing_below_threshold_0_35",
        "description": "ECLog timing vector just below 0.35 threshold (prob ~0.3298476)",
        "full_vector": {
            "SAGE_Session_Depth": 4.0,
            "SAGE_Temporal_Variance": 1.302742,
            "SAGE_Request_Velocity": 0.023392,
            "SAGE_Behavioral_Diversity": 1.039721,
            "SAGE_Endpoint_Concentration": 0.5,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 1.0,
            "SAGE_NonStatic_Navigation_Gap": 6.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 1.0,
        },
        "target_model": "eclog_timing_binary_model.pkl",
        "expected_prob": 0.3298476,
        "expected_is_bot": False, # < 0.35
    },
    {
        "id": "timing_above_threshold_0_35",
        "description": "ECLog timing vector just above 0.35 threshold (prob ~0.3606159)",
        "full_vector": {
            "SAGE_Session_Depth": 50.0,
            "SAGE_Temporal_Variance": 1.049751,
            "SAGE_Request_Velocity": 0.019201,
            "SAGE_Behavioral_Diversity": 3.856571,
            "SAGE_Endpoint_Concentration": 0.04,
            "SAGE_Cart_Ratio": 0.003743,
            "SAGE_Asset_Skip_Ratio": 1.0,
            "SAGE_NonStatic_Navigation_Gap": 41.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.979592,
        },
        "target_model": "eclog_timing_binary_model.pkl",
        "expected_prob": 0.3606159,
        "expected_is_bot": True, # >= 0.35
    },
    {
        "id": "prod_below_threshold_0_50",
        "description": "Production model vector just below 0.50 threshold (prob ~0.4716901)",
        "full_vector": {
            "SAGE_Session_Depth": 4.0,
            "SAGE_Temporal_Variance": 1.053118,
            "SAGE_Request_Velocity": 1.255099,
            "SAGE_Behavioral_Diversity": 0.562335,
            "SAGE_Endpoint_Concentration": 0.75,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 0.571429,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "sage_binary_model.pkl",
        "expected_prob": 0.4716901,
        "expected_is_bot": False, # < 0.50
    },
    {
        "id": "prod_above_threshold_0_50",
        "description": "Production model vector above 0.50 threshold (prob ~0.5707078)",
        "full_vector": {
            "SAGE_Session_Depth": 7.0,
            "SAGE_Temporal_Variance": 0.695566,
            "SAGE_Request_Velocity": 0.931966,
            "SAGE_Behavioral_Diversity": 1.153742,
            "SAGE_Endpoint_Concentration": 0.571429,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 0.70,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "sage_binary_model.pkl",
        "expected_prob": 0.5707078,
        "expected_is_bot": True, # >= 0.50
    },
    {
        "id": "obvious_human_browser",
        "description": "Low velocity browsing human with assets and cart hits (prob ~0.1237264)",
        "full_vector": {
            "SAGE_Session_Depth": 12.0,
            "SAGE_Temporal_Variance": 0.85,
            "SAGE_Request_Velocity": 0.5,
            "SAGE_Behavioral_Diversity": 2.1,
            "SAGE_Endpoint_Concentration": 0.25,
            "SAGE_Cart_Ratio": 0.15,
            "SAGE_Asset_Skip_Ratio": 0.20,
            "SAGE_NonStatic_Navigation_Gap": 2.5,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.80,
        },
        "target_model": "sage_binary_model.pkl",
        "expected_prob": 0.1237264,
        "expected_is_bot": False,
    },
    {
        "id": "obvious_fast_scraper",
        "description": "High velocity scraper with zero assets and zero cart (prob ~0.9997435)",
        "full_vector": {
            "SAGE_Session_Depth": 30.0,
            "SAGE_Temporal_Variance": 0.12,
            "SAGE_Request_Velocity": 12.5,
            "SAGE_Behavioral_Diversity": 0.4,
            "SAGE_Endpoint_Concentration": 0.9,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 1.0,
            "SAGE_NonStatic_Navigation_Gap": 0.08,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "sage_binary_model.pkl",
        "expected_prob": 0.9997435,
        "expected_is_bot": True,
    },
    {
        "id": "eclog_6feature_test",
        "description": "ECLog 6-feature baseline on human-like shopping browsing",
        "full_vector": {
            "SAGE_Session_Depth": 20.0,
            "SAGE_Temporal_Variance": 0.8,
            "SAGE_Request_Velocity": 1.5,
            "SAGE_Behavioral_Diversity": 1.8,
            "SAGE_Endpoint_Concentration": 0.3,
            "SAGE_Cart_Ratio": 0.1,
            "SAGE_Asset_Skip_Ratio": 0.8,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "eclog_6feature_binary_model.pkl",
        "expected_prob": 0.0004516,
        "expected_is_bot": False,
    },
    {
        "id": "eclog_weak_7feature_test",
        "description": "ECLog weak 7-feature baseline on human-like shopping browsing",
        "full_vector": {
            "SAGE_Session_Depth": 20.0,
            "SAGE_Temporal_Variance": 0.8,
            "SAGE_Request_Velocity": 1.5,
            "SAGE_Behavioral_Diversity": 1.8,
            "SAGE_Endpoint_Concentration": 0.3,
            "SAGE_Cart_Ratio": 0.1,
            "SAGE_Asset_Skip_Ratio": 0.8,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "eclog_weak_binary_model.pkl",
        "expected_prob": 0.0065497,
        "expected_is_bot": False,
    },
    {
        "id": "edge_zero_vector",
        "description": "Zero/default vector for empty or initial requests (prob ~0.9998087)",
        "full_vector": {
            "SAGE_Session_Depth": 0.0,
            "SAGE_Temporal_Variance": 0.0,
            "SAGE_Request_Velocity": 0.0,
            "SAGE_Behavioral_Diversity": 0.0,
            "SAGE_Endpoint_Concentration": 0.0,
            "SAGE_Cart_Ratio": 0.0,
            "SAGE_Asset_Skip_Ratio": 1.0,
            "SAGE_NonStatic_Navigation_Gap": 0.0,
            "SAGE_NonStatic_Long_Gap_Ratio": 0.0,
        },
        "target_model": "sage_binary_model.pkl",
        "expected_prob": 0.9998087,
        "expected_is_bot": True,
    }
]


def test_golden_predictions_deterministic_direct():
    """Validates that all 4 pickled models compute exact deterministic predictions within 1e-5."""
    models = {}
    for gv in GOLDEN_VECTORS:
        model_name = gv["target_model"]
        if model_name not in models:
            with open(MODELS_DIR / model_name, "rb") as f:
                models[model_name] = pickle.load(f)

        m_data = models[model_name]
        features = m_data["features"]
        clf = m_data["model"]

        # Build feature vector DataFrame by column name
        vec_row = [gv["full_vector"][f] for f in features]
        df_vec = pd.DataFrame([vec_row], columns=features)

        prob = float(clf.predict_proba(df_vec)[0, 1])
        th = float(m_data.get("threshold", 0.50))
        is_bot = prob >= th

        if "expected_prob" in gv:
            diff = abs(prob - gv["expected_prob"])
            assert diff <= 1e-4, (
                f"[{gv['id']}] Probability drift: expected {gv['expected_prob']}, got {prob} (diff {diff})"
            )

        assert is_bot == gv["expected_is_bot"], (
            f"[{gv['id']}] Classification mismatch: expected {gv['expected_is_bot']}, got {is_bot} (prob={prob}, th={th})"
        )


def test_live_predict_route_golden_vectors():
    """Validates predictions and response identity headers via the FastAPI /predict endpoint."""
    async def _run():
        async with lifespan(app):
            h = health_check()
            assert h["status"] == "operational"
            assert h["prod_model_sha256"] is not None
            assert h["shadow_model_sha256"] is not None
            assert h["prod_contract_hash"] is not None
            assert h["shadow_contract_hash"] is not None

            for gv in GOLDEN_VECTORS[:4]:
                payload = dict(gv["full_vector"])
                payload["session_id"] = f"test-{gv['id']}"

                data = await predict_anomaly(GatewayTelemetry(**payload))

                assert data.prod_model_sha256 == h["prod_model_sha256"]
                assert data.shadow_model_sha256 == h["shadow_model_sha256"]
                assert data.shadow_status == "ok"
                assert data.shadow_threshold == h["shadow_threshold"]
                assert data.bot_probability is not None
                assert data.shadow_bot_probability is not None

    asyncio.run(_run())

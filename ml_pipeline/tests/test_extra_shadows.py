"""Multi-shadow scoring (audit N25): extra shadow models are manifest-verified and scored on every request."""

import asyncio
import json
import pickle
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE_DIR / "ml_pipeline" / "models"
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "inference_service"))
import main as svc  # noqa: E402

V7 = "eclog6m_prefix_8feature_v1.pkl"
VECTOR = {
    "session_id": "t", "SAGE_Session_Depth": 30.0, "SAGE_Temporal_Variance": 0.4, "SAGE_Request_Velocity": 3.0,
    "SAGE_Behavioral_Diversity": 2.1, "SAGE_Endpoint_Concentration": 0.3, "SAGE_Cart_Ratio": 0.0,
    "SAGE_Asset_Skip_Ratio": 1.0, "SAGE_NonStatic_Navigation_Gap": 0.5, "SAGE_NonStatic_Long_Gap_Ratio": 0.2,
}


def run(env_files):
    async def go():
        async with svc.lifespan(svc.app):
            return await svc.predict_anomaly(svc.GatewayTelemetry(**VECTOR)), svc.health_check()
    import os
    os.environ["EXTRA_SHADOW_MODEL_FILES"] = env_files
    try:
        return asyncio.run(go())
    finally:
        del os.environ["EXTRA_SHADOW_MODEL_FILES"]


def test_extra_shadow_matches_direct_scoring_and_manifest():
    result, health = run(V7)
    (extra,) = result.extra_shadows
    d = pickle.loads((MODELS_DIR / V7).read_bytes())
    p = float(d["model"].predict_proba(pd.DataFrame([[VECTOR[f] for f in d["features"]]], columns=d["features"]))[0][1])
    manifest = json.loads((MODELS_DIR / "frozen_models_manifest_v7.json").read_text())["models"][V7[:-4]]
    assert extra["status"] == "ok"
    assert extra["bot_probability"] == pytest.approx(p, abs=1e-6)
    assert extra["is_bot"] == (p >= d["threshold"])
    assert extra["model_sha256"] == manifest["sha256"]
    assert extra["name"] == V7[:-4]
    assert result.shadow_status == "ok"  # the original prod + shadow path is untouched
    assert health["extra_shadows"][0]["sha256"] == manifest["sha256"]


def test_no_extra_shadows_by_default():
    result, health = run("")
    assert result.extra_shadows == [] and health["extra_shadows"] == []


def test_unmanifested_extra_shadow_is_refused(monkeypatch):
    monkeypatch.setattr(svc, "load_frozen_sha", lambda model_dir, key: None)
    with pytest.raises(RuntimeError, match="not in any frozen manifest"):
        run(V7)


def test_hash_mismatch_is_refused_before_unpickling(monkeypatch):
    monkeypatch.setattr(svc, "load_frozen_sha", lambda model_dir, key: "0" * 64)
    real_loads, v7_bytes = svc.pickle.loads, (MODELS_DIR / V7).read_bytes()
    monkeypatch.setattr(svc.pickle, "loads",
                        lambda b: pytest.fail("unpickled before the hash check") if b == v7_bytes else real_loads(b))
    with pytest.raises(RuntimeError, match="hash mismatch"):
        run(V7)


def test_model_without_threshold_is_refused():
    with pytest.raises(RuntimeError, match="no frozen threshold"):
        run("eclog_6feature_binary_model.pkl")

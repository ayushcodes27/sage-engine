"""
test_clopper_pearson_and_config.py

Unit tests asserting:
1. Exact Clopper-Pearson 95% confidence intervals:
   - 0/20 upper ~0.168
   - 0/200 upper ~0.0183
   - 20/20 lower ~0.832
2. Campaign configuration hashing and gate sensitivity:
   - Changing a threshold in final_campaign_config.json changes the SHA-256 hash.
   - Changing a threshold changes the evaluator gate outcome (PASS -> FAIL).
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import pandas as pd

from ml_pipeline.scripts.evaluate.evaluate_shadow import (
    clopper_pearson_ci,
    build_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "final_campaign_config.json"


def test_clopper_pearson_exact_intervals():
    # 0/20 upper ~0.168
    p, low, up = clopper_pearson_ci(0, 20)
    assert p == 0.0
    assert low == 0.0
    assert round(up, 3) == 0.168
    assert pytest.approx(0.1684, abs=0.001) == up

    # 0/200 upper ~0.0183
    p, low, up = clopper_pearson_ci(0, 200)
    assert p == 0.0
    assert low == 0.0
    assert round(up, 4) == 0.0183
    assert pytest.approx(0.01828, abs=0.0001) == up

    # 20/20 lower ~0.832
    p, low, up = clopper_pearson_ci(20, 20)
    assert p == 1.0
    assert round(low, 3) == 0.832
    assert pytest.approx(0.8316, abs=0.001) == low
    assert up == 1.0


def test_campaign_config_hash_and_gate_outcome():
    assert CONFIG_PATH.exists(), f"Missing {CONFIG_PATH}"
    orig_bytes = CONFIG_PATH.read_bytes()
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()
    orig_cfg = json.loads(orig_bytes.decode("utf-8"))

    # Assert base hash is genuine sha256 (64 hex characters) and not legacy mock
    assert len(orig_hash) == 64
    assert orig_hash != "f929cb23fa46d51c356b6c085f36e8aa"

    # 1. Mutate threshold: macro_average_bot_recall_min or human_fpr_limit
    mutated_cfg = copy.deepcopy(orig_cfg)
    mutated_cfg["gate_thresholds"]["macro_average_bot_recall_min"] = 0.999
    mutated_bytes = json.dumps(mutated_cfg, indent=2).encode("utf-8")
    mutated_hash = hashlib.sha256(mutated_bytes).hexdigest()

    # Changing threshold MUST change hash
    assert mutated_hash != orig_hash

    # 2. Test gate outcome sensitivity using synthetic evaluation payload
    run_id = "test-gate-sensitivity"
    client_manifest = {
        "human-01": {"client_id": "human-01", "profile": "normal_browser", "expected_label": "human", "true_class": "human"},
        "bot-01": {"client_id": "bot-01", "profile": "slow_scraper", "expected_label": "bot", "true_class": "bot"},
        "bot-02": {"client_id": "bot-02", "profile": "asset_fetching_bot", "expected_label": "bot", "true_class": "bot"},
        "bot-03": {"client_id": "bot-03", "profile": "fast_scraper", "expected_label": "bot", "true_class": "bot"},
    }
    
    manifest_base = {
        "run_id": run_id,
        "run_mode": "final",
        "campaign_config_hash": orig_hash,
        "campaign_config": orig_cfg,
        "clients": client_manifest,
    }

    # Telemetry: 1 human with 0 bot detections (FPR=0%), 3 bots with 100% recall (macro bot recall = 100%)
    active_tuple = {
        "prod_model_sha256": "a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f",
        "shadow_model_sha256": "7b29ee3b555891ceeaeeea9b49195e347ee9fa75eef501df78996feea9f5eef1",
        "shadow_contract_hash": "2fb47afb4dae24d35eef4bbdb0374eec7f5baefdfa1334c2d3989c743818e3e4",
        "shadow_feature_list_hash": "a4d348a0a9966ee4e46045ca6e1a49f7cf7c9ff381c81ef40d426fe4f8303f83",
        "shadow_threshold": 0.35,
    }
    telemetry_rows = [
        {
            "event_id": f"evt-{cid}",
            "run_id": run_id,
            "client_id": cid,
            "path": "/products/1",
            "status": 200,
            "bot_prob": 0.01 if "human" in cid else 0.90,
            "is_bot": "bot" in cid,
            "shadow_prob": 0.01 if "human" in cid else 0.95,
            "shadow_is_bot": "bot" in cid,
            "shadow_action": "Allowed" if "human" in cid else "Blocked",
            "shadow_status": "ok",
            "prod_latency": 10.0,
            "shadow_latency": 15.0,
            "contract_hash": "c",
            "model_version": "v1",
            "evaluation_status": "Scored",
            "scoring_depth": 25,
            "session_depth": 25,
            "navigation_gap": 1.2,
            "long_gap_ratio": 0.5,
            "feature_vector_present": True,
            **active_tuple,
        }
        for cid in client_manifest
    ]
    telemetry_df = pd.DataFrame(telemetry_rows)

    frozen_manifest = {"active_deployment": active_tuple}

    # Evaluate with original config thresholds (macro_average_bot_recall_min=0.90, human_fpr_limit=0.10)
    report_pass, passed_orig = build_report(
        manifest_base,
        client_manifest,
        telemetry_df,
        1000,
        frozen_manifest=frozen_manifest,
        run_mode="final",
    )
    assert passed_orig is True

    # Evaluate with mutated strict threshold that fails observed performance (e.g. human_fpr_limit=-0.01)
    manifest_mutated = copy.deepcopy(manifest_base)
    manifest_mutated["campaign_config_hash"] = mutated_hash
    manifest_mutated["campaign_config"] = mutated_cfg
    mutated_cfg["gate_thresholds"]["human_fpr_limit"] = -0.01  # Impossible to satisfy

    report_fail, passed_mutated = build_report(
        manifest_mutated,
        client_manifest,
        telemetry_df,
        1000,
        frozen_manifest=frozen_manifest,
        run_mode="final",
    )
    assert passed_mutated is False

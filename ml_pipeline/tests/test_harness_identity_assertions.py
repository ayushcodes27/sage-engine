"""
test_harness_identity_assertions.py

Automated tests asserting evaluator behavior under:
1. Valid tagged identity match
2. Hash mismatch against expected manifest
3. Missing metadata on scored records
4. Production-hash-only (legacy payloads)
5. Mixed identities across scored records
6. Unscored records handled separately (not failing the identity gate)
"""

import json
import pytest
import pandas as pd
from ml_pipeline.scripts.evaluate.evaluate_shadow import verify_identity_assertions


@pytest.fixture
def expected_identity():
    return {
        "prod_model_sha256": "a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f",
        "shadow_model_sha256": "ed184cb9d93ae700b6d395a81a81ae1dbcd159b07b23f7c6a5b3b83644023ebc",
        "shadow_contract_hash": "4e8b01ac1b96952c3ad35b86e80948dafb296fb9306815c5fb807c3012a7222c",
        "shadow_feature_list_hash": "efbc867d297e1d93fad34781cc7f24161826db9ada57046258ac8198b890e854",
        "shadow_threshold": 0.35,
    }


def make_row(shadow_status="ok", shadow_prob=0.85, shadow_is_bot=True, **identity_overrides):
    base = {
        "event_id": "evt-1",
        "shadow_status": shadow_status,
        "shadow_prob": shadow_prob,
        "shadow_is_bot": shadow_is_bot,
        "prod_model_sha256": "a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f",
        "shadow_model_sha256": "ed184cb9d93ae700b6d395a81a81ae1dbcd159b07b23f7c6a5b3b83644023ebc",
        "shadow_contract_hash": "4e8b01ac1b96952c3ad35b86e80948dafb296fb9306815c5fb807c3012a7222c",
        "shadow_feature_list_hash": "efbc867d297e1d93fad34781cc7f24161826db9ada57046258ac8198b890e854",
        "shadow_threshold": 0.35,
    }
    base.update(identity_overrides)
    return base


def test_valid_identity_match(expected_identity):
    rows = [make_row(event_id=f"evt-{i}") for i in range(10)]
    df = pd.DataFrame(rows)

    is_valid, errors, scored_count, unscored_count = verify_identity_assertions(df, expected_identity)
    assert is_valid is True
    assert len(errors) == 0
    assert scored_count == 10
    assert unscored_count == 0


def test_hash_mismatch_fails(expected_identity):
    # Telemetry has different shadow model hash
    rows = [make_row(shadow_model_sha256="deadbeef" * 8)]
    df = pd.DataFrame(rows)

    is_valid, errors, scored_count, _ = verify_identity_assertions(df, expected_identity)
    assert is_valid is False
    assert any("does not match tagged manifest" in e for e in errors)
    assert scored_count == 1


def test_missing_metadata_on_scored_record_fails(expected_identity):
    # Scored record with None shadow_model_sha256
    rows = [
        make_row(event_id="evt-1"),
        make_row(event_id="evt-2", shadow_model_sha256=None),
    ]
    df = pd.DataFrame(rows)

    is_valid, errors, scored_count, _ = verify_identity_assertions(df, expected_identity)
    assert is_valid is False
    assert any("missing complete cryptographic identity tuple" in e for e in errors)


def test_production_hash_only_fails(expected_identity):
    # Legacy event where prod hash is present but shadow fields are null/None
    rows = [
        make_row(
            shadow_model_sha256=None,
            shadow_contract_hash=None,
            shadow_feature_list_hash=None,
        )
    ]
    df = pd.DataFrame(rows)

    is_valid, errors, _, _ = verify_identity_assertions(df, expected_identity)
    assert is_valid is False
    assert any("missing complete cryptographic identity tuple" in e for e in errors)


def test_mixed_identities_fails(expected_identity):
    # Two scored events with different shadow hashes
    rows = [
        make_row(event_id="evt-1"),
        make_row(event_id="evt-2", shadow_model_sha256="7b29ee3b574ce43cf9984408ff2d19096a6205c6389deff907cebf67e8e7f193"),
    ]
    df = pd.DataFrame(rows)

    is_valid, errors, scored_count, _ = verify_identity_assertions(df, expected_identity)
    assert is_valid is False
    assert any("Mixed identities detected" in e for e in errors)
    assert scored_count == 2


def test_unscored_records_do_not_fail_identity_gate(expected_identity):
    # 5 scored records (valid), plus 10 unscored records with skipped status and null identity
    scored_rows = [make_row(event_id=f"evt-s-{i}") for i in range(5)]
    unscored_rows = [
        {
            "event_id": f"evt-u-{i}",
            "shadow_status": "skipped",
            "shadow_prob": None,
            "shadow_is_bot": None,
            "prod_model_sha256": None,
            "shadow_model_sha256": None,
            "shadow_contract_hash": None,
            "shadow_feature_list_hash": None,
            "shadow_threshold": None,
        }
        for i in range(10)
    ]
    df = pd.DataFrame(scored_rows + unscored_rows)

    is_valid, errors, scored_count, unscored_count = verify_identity_assertions(df, expected_identity)
    assert is_valid is True
    assert len(errors) == 0
    assert scored_count == 5
    assert unscored_count == 10


def test_manifest_active_deployment_matches_intended_shadow_model_table_row():
    from pathlib import Path
    manifest_path = Path(__file__).resolve().parents[1] / "models" / "frozen_models_manifest.json"
    assert manifest_path.exists(), f"Manifest not found at {manifest_path}"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    assert "intended_shadow_model" in manifest, "Manifest must declare intended_shadow_model"
    intended = manifest["intended_shadow_model"]
    assert intended == "eclog_timing_binary_model", f"Expected intended shadow eclog_timing_binary_model, got {intended}"
    
    active = manifest.get("active_deployment", {})
    assert active.get("shadow_model_name") == intended, "active_deployment.shadow_model_name must match intended_shadow_model"
    
    # Assert model SHA matches model table row exactly
    models = manifest.get("models", {})
    assert intended in models, f"Model {intended} missing from manifest models table"
    expected_model_sha = models[intended]["sha256"]
    assert active.get("shadow_model_sha256") == expected_model_sha, (
        f"active_deployment.shadow_model_sha256 ({active.get('shadow_model_sha256')}) "
        f"does not match model table row ({expected_model_sha})"
    )
    
    # Assert contract hash and feature list hash match contract table row
    contracts = manifest.get("contracts", {})
    contract_name = active.get("shadow_contract_name")
    assert contract_name == "contract_eclog_timing_8feat", f"Unexpected shadow contract name: {contract_name}"
    assert contract_name in contracts, f"Contract {contract_name} missing from contracts table"
    
    expected_contract_sha = contracts[contract_name]["sha256"]
    expected_feat_list_sha = contracts[contract_name]["feature_list_sha256"]
    
    assert active.get("shadow_contract_hash") == expected_contract_sha, (
        f"active_deployment.shadow_contract_hash ({active.get('shadow_contract_hash')}) "
        f"does not match contract table row ({expected_contract_sha})"
    )
    assert active.get("shadow_feature_list_hash") == expected_feat_list_sha, (
        f"active_deployment.shadow_feature_list_hash ({active.get('shadow_feature_list_hash')}) "
        f"does not match contract table row ({expected_feat_list_sha})"
    )
    
    # Assert 8 features including Navigation_Gap and Long_Gap_Ratio
    feat_list = contracts[contract_name]["features"]
    assert len(feat_list) == 8, f"Expected 8 features for timing model, found {len(feat_list)}"
    assert "SAGE_NonStatic_Navigation_Gap" in feat_list
    assert "SAGE_NonStatic_Long_Gap_Ratio" in feat_list


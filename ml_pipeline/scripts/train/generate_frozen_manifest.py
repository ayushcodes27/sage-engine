#!/usr/bin/env python3
"""
generate_frozen_manifest.py

Generates cryptographic frozen manifest for all production and shadow models,
contracts, feature lists, thresholds, datasets, and scoring-path code.
"""

import hashlib
import json
import math
import os
import pickle
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR.parent
MODELS_DIR = BASE_DIR / "models"
CONTRACTS_DIR = MODELS_DIR / "contracts"
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = MODELS_DIR / "frozen_models_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sanitize_param(val):
    if isinstance(val, float) and math.isnan(val):
        return None
    if hasattr(val, "item"):
        val = val.item()
    if isinstance(val, (int, float, str, bool, list, dict)) or val is None:
        return val
    return str(val)


def inspect_model(model_rel_path: str):
    full_path = REPO_ROOT / model_rel_path
    data_bytes = full_path.read_bytes()
    file_sha256 = sha256_bytes(data_bytes)
    
    data = pickle.loads(data_bytes)
    model_obj = data["model"]
    features = data.get("features", [])
    classes = [int(c) if hasattr(c, "item") else c for c in data.get("classes", [])]
    
    raw_params = model_obj.get_params() if hasattr(model_obj, "get_params") else {}
    params = {k: sanitize_param(v) for k, v in raw_params.items()}
    
    return {
        "relative_path": model_rel_path.replace("\\", "/"),
        "sha256": file_sha256,
        "features": features,
        "classes": classes,
        "hyperparameters": params,
        "random_state": params.get("random_state", 42),
    }


def inspect_contract(contract_rel_path: str):
    full_path = REPO_ROOT / contract_rel_path
    content = full_path.read_text(encoding="utf-8")
    file_sha256 = sha256_bytes(content.encode("utf-8"))
    doc = json.loads(content)
    
    feature_list = doc.get("features", [])
    feature_list_bytes = json.dumps(feature_list, separators=(",", ":")).encode("utf-8")
    feature_list_hash = sha256_bytes(feature_list_bytes)
    
    return {
        "relative_path": contract_rel_path.replace("\\", "/"),
        "contract_name": doc.get("contract_name"),
        "contract_version": doc.get("contract_version"),
        "sha256": file_sha256,
        "feature_count": len(feature_list),
        "features": feature_list,
        "feature_list_sha256": feature_list_hash,
    }


def get_pip_freeze() -> str:
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"Warning: pip freeze failed: {e}")
        return ""


def get_mvn_tree() -> str:
    gateway_dir = REPO_ROOT / "sage-gateway"
    mvnw = gateway_dir / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    if not mvnw.exists():
        return ""
    try:
        res = subprocess.run(
            [str(mvnw), "-f", str(gateway_dir / "pom.xml"), "dependency:tree", "-DoutputType=text"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"Warning: mvn dependency:tree failed: {e}")
        return ""


def main():
    print("Generating Frozen Models Manifest...")
    
    # 1. Models
    models = {
        "sage_binary_model": inspect_model("ml_pipeline/models/sage_binary_model.pkl"),
        "eclog_weak_binary_model": inspect_model("ml_pipeline/models/eclog_weak_binary_model.pkl"),
        "eclog_6feature_binary_model": inspect_model("ml_pipeline/models/eclog_6feature_binary_model.pkl"),
        "eclog_timing_binary_model": inspect_model("ml_pipeline/models/eclog_timing_binary_model.pkl"),
    }
    
    # 2. Contracts
    contracts = {
        "contract_prod_7feat": inspect_contract("ml_pipeline/models/contracts/contract_prod_7feat.json"),
        "contract_eclog_6feat": inspect_contract("ml_pipeline/models/contracts/contract_eclog_6feat.json"),
        "contract_eclog_timing_8feat": inspect_contract("ml_pipeline/models/contracts/contract_eclog_timing_8feat.json"),
    }
    
    # 3. Datasets & Splits
    datasets = {
        "training_data_csv": {
            "relative_path": "ml_pipeline/data/training_data.csv",
            "sha256": sha256_file(REPO_ROOT / "ml_pipeline/data/training_data.csv"),
        },
        "eclog_weak_labeled_csv": {
            "relative_path": "ml_pipeline/data/eclog_weak_labeled.csv",
            "sha256": sha256_file(REPO_ROOT / "ml_pipeline/data/eclog_weak_labeled.csv"),
        },
        "sage_binary_split_manifest": {
            "relative_path": "ml_pipeline/models/sage_binary_split_manifest.json",
            "sha256": sha256_file(REPO_ROOT / "ml_pipeline/models/sage_binary_split_manifest.json"),
        },
        "eclog_weak_split_manifest": {
            "relative_path": "ml_pipeline/models/eclog_weak_split_manifest.json",
            "sha256": sha256_file(REPO_ROOT / "ml_pipeline/models/eclog_weak_split_manifest.json"),
        },
    }
    
    # 4. Scoring-Path Code & Threshold in application.yaml
    scoring_code = {
        "main_service": {
            "relative_path": "ml_pipeline/inference_service/main.py",
            "sha256": sha256_file(REPO_ROOT / "ml_pipeline/inference_service/main.py"),
        },
        "redis_telemetry_service": {
            "relative_path": "sage-gateway/src/main/java/com/sage/gateway/service/RedisTelemetryService.java",
            "sha256": sha256_file(REPO_ROOT / "sage-gateway/src/main/java/com/sage/gateway/service/RedisTelemetryService.java"),
        },
        "ml_inference_filter": {
            "relative_path": "sage-gateway/src/main/java/com/sage/gateway/filter/MLInferenceFilter.java",
            "sha256": sha256_file(REPO_ROOT / "sage-gateway/src/main/java/com/sage/gateway/filter/MLInferenceFilter.java"),
        },
        "application_yaml": {
            "relative_path": "sage-gateway/src/main/resources/application.yaml",
            "sha256": sha256_file(REPO_ROOT / "sage-gateway/src/main/resources/application.yaml"),
        },
    }
    
    # Explicit Frozen File List
    frozen_files = {}
    for m in models.values():
        frozen_files[m["relative_path"]] = m["sha256"]
    for c in contracts.values():
        frozen_files[c["relative_path"]] = c["sha256"]
    for d in datasets.values():
        frozen_files[d["relative_path"]] = d["sha256"]
    for s in scoring_code.values():
        frozen_files[s["relative_path"]] = s["sha256"]

    # 5. Threshold Provenance
    threshold_provenance = {
        "value": 0.35,
        "methodology": "Selected on out-of-fold (OOF) cross-validation on the training data grouped by IpId (5-fold GroupKFold), before holdout evaluation and before the 140-client campaign.",
        "split_grouping": "grouped by IpId",
        "verified_before_campaign": True,
        "notes": "Verified from git commit and run timestamps prior to any shadow traffic campaign. Not stratified, not selected on holdout.",
    }
    
    # 6. Active Deployment Identity Tuple
    active_deployment = {
        "prod_model_name": "sage_binary_model",
        "shadow_model_name": "eclog_timing_binary_model",
        "prod_model_sha256": models["sage_binary_model"]["sha256"],
        "shadow_model_sha256": models["eclog_timing_binary_model"]["sha256"],
        "shadow_contract_name": "contract_eclog_timing_8feat",
        "shadow_contract_hash": contracts["contract_eclog_timing_8feat"]["sha256"],
        "shadow_feature_list_hash": contracts["contract_eclog_timing_8feat"]["feature_list_sha256"],
        "shadow_threshold": 0.35,
    }
    
    # 7. Environment Dependencies
    pip_freeze_out = get_pip_freeze()
    mvn_tree_out = get_mvn_tree()
    
    manifest = {
        "manifest_version": "2.0",
        "tag": "v2-frozen-models-v4",
        "intended_shadow_model": "eclog_timing_binary_model",
        "threshold_provenance": threshold_provenance,
        "active_deployment": active_deployment,
        "models": models,
        "contracts": contracts,
        "datasets": datasets,
        "scoring_code": scoring_code,
        "frozen_files": frozen_files,
        "environment": {
            "pip_freeze_sha256": sha256_bytes(pip_freeze_out.encode("utf-8")),
            "mvn_tree_sha256": sha256_bytes(mvn_tree_out.encode("utf-8")),
            "pip_freeze": pip_freeze_out,
            "mvn_tree": mvn_tree_out,
        },
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    print(f"Manifest written to {OUTPUT_FILE}")
    print(f"Total frozen files tracked: {len(frozen_files)}")
    print(f"Active deployment tuple: {json.dumps(active_deployment, indent=2)}")


if __name__ == "__main__":
    main()

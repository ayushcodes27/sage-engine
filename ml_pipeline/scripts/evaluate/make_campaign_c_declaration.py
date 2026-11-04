#!/usr/bin/env python3
"""
Writes everything campaign C is declared by, BEFORE any campaign traffic exists:

  configs/campaign_c_v1_s{1,2,3}.json        generator configs (300 humans = 75 x 4 profiles, 150 bots = 50 x 3)
  ml_pipeline/models/scoring_manifest_campaign_c_v1.json
                                             identity the generator asserts against /health: the v6 prod + timing
                                             shadow (as runs A/B) plus the v7 prefix model as additional shadow
  configs/campaign_c_declaration_v1.json     hashes of every model/config/script involved, thresholds, the grading plan

Uses VALIDATION data only (secondary operating point of the v7 model); no test-split or campaign number is computed.
"""

import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "evaluate"))
from evaluate_eclog6m import proba  # noqa: E402
from make_eclog6m_split import SESSIONS_6M, split_of  # noqa: E402
from offline_metrics import client_table, confusion, threshold_at_fpr  # noqa: E402

MODELS = REPO / "ml_pipeline" / "models"
V7_NAME = "eclog6m_prefix_8feature_v1"
HUMAN_PROFILES = ["normal_browser", "spa_client", "mobile_browser", "privacy_browser"]
BOT_PROFILES = ["slow_scraper", "asset_fetching_bot", "fast_scraper"]
SEED_SETS = {1: 9100, 2: 9200, 3: 9300}  # seed set 1 equals runs A/B (9101..9107)
SECONDARY_VALIDATION_FPR = 0.001


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(p):
    return str(Path(p).relative_to(REPO))


def main():
    orig = json.loads((REPO / "final_campaign_config.json").read_text())
    v6 = json.loads((MODELS / "frozen_models_manifest.json").read_text())
    v7 = json.loads((MODELS / "frozen_models_manifest_v7.json").read_text())
    d7 = pickle.loads((MODELS / f"{V7_NAME}.pkl").read_bytes())

    # secondary operating point: smallest threshold with VALIDATION client FPR <= 0.1 %
    sessions = pd.read_csv(SESSIONS_6M)
    sessions["split"] = sessions["IpId"].map(split_of(sessions["IpId"]))
    val = sessions[(sessions["scored"] == 1) & (sessions["label"] != "unknown") & (sessions["split"] == "validation")]
    vc, _ = client_table(val, proba(d7, val, "pre_"))
    t_sec = threshold_at_fpr(vc.loc[vc["y"] == 0, "score"], SECONDARY_VALIDATION_FPR)
    val_cm = {"frozen_threshold": confusion(vc["y"], vc["score"], d7["threshold"]),
              "secondary_threshold": confusion(vc["y"], vc["score"], t_sec)}

    configs = {}
    for n, base in SEED_SETS.items():
        cfg = {k: v for k, v in orig.items() if k != "profile_seeds"}
        cfg["campaign"] = f"campaign_c_v1_s{n}"
        cfg["clients_per_profile_overrides"] = {**{p: 75 for p in HUMAN_PROFILES}, **{p: 50 for p in BOT_PROFILES}}
        cfg["profile_seeds"] = {p: base + i + 1 for i, p in enumerate(orig["profiles"])}
        path = REPO / "configs" / f"campaign_c_v1_s{n}.json"
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        configs[f"seed_set_{n}"] = {"path": rel(path), "sha256": sha(path), "profile_seeds": cfg["profile_seeds"]}
    assert configs["seed_set_1"]["profile_seeds"] == orig["profile_seeds"], "seed set 1 must equal runs A/B"

    extra = {"name": V7_NAME, "file": f"{V7_NAME}.pkl", "sha256": sha(MODELS / f"{V7_NAME}.pkl"),
             "contract_hash": d7["contract_hash"],
             "feature_list_hash": v7["feature_list_sha256"], "threshold": d7["threshold"]}
    assert v7["models"][V7_NAME]["sha256"] == extra["sha256"]
    scoring = {"manifest_version": "campaign_c_v1",
               "note": "identity the generator asserts against the sage-ml /health endpoint before and after the run",
               "active_deployment": {**v6["active_deployment"], "extra_shadows": [extra]}}
    sm_path = MODELS / "scoring_manifest_campaign_c_v1.json"
    sm_path.write_text(json.dumps(scoring, indent=2) + "\n")

    files = {
        "models": {p.name: sha(p) for p in sorted(MODELS.glob("*.pkl"))},
        "frozen_manifests": {p.name: sha(p) for p in sorted(MODELS.glob("frozen_models_manifest*.json"))},
        "contracts": {p.name: sha(p) for p in sorted((MODELS / "contracts").glob("*.json"))},
        "scoring_manifest": {"path": rel(sm_path), "sha256": sha(sm_path)},
        "original_gates": {"path": "final_campaign_config.json", "sha256": sha(REPO / "final_campaign_config.json")},
        "revised_gates": {"path": "configs/gates_revised_v1.json", "sha256": sha(REPO / "configs" / "gates_revised_v1.json")},
        "protocols": {p: sha(REPO / "configs" / p) for p in ("offline_protocol_v1.json", "offline_protocol_v1_1.json",
                                                              "offline_protocol_v1_2_resolution.json",
                                                              "split_eclog6m_v1.json")},
        "code": {p: sha(REPO / p) for p in (
            "load-tests/diverse-shadow-traffic.py", "ml_pipeline/inference_service/main.py",
            "ml_pipeline/scripts/evaluate/campaign_metrics.py", "ml_pipeline/scripts/evaluate/evaluate_shadow.py",
            "ml_pipeline/scripts/evaluate/regrade_campaigns.py", "infra/docker-compose.yml",
            "sage-gateway/src/main/resources/application.yaml",
            "sage-gateway/src/main/resources/application-docker.properties")},
    }
    decl = {
        "name": "campaign_c_v1",
        "status": "declared before any campaign C traffic; the numbers below are validation-only",
        "design": {"humans": 300, "bots": 150, "per_human_profile": 75, "per_bot_profile": 50,
                   "profiles": orig["profiles"], "traffic": "same generator and profile logic as runs A/B",
                   "seed_sets": configs, "runs": "seed set 1 is the primary campaign; sets 2 and 3 run only if time allows "
                                                  "and are reported as replicates, never selected between"},
        "models_graded": {
            "prod_sage_binary_7feat": {"threshold": 0.5, "source": "service pickle"},
            "shadow_eclog_timing_8feat": {"threshold": 0.35, "note": "v6 frozen, as runs A/B"},
            f"extra:{V7_NAME}@frozen": {"threshold": d7["threshold"], "primary_for_v7": True,
                                        "note": "threshold chosen on the six-month VALIDATION split (client FPR <= 1 %)"},
            f"extra:{V7_NAME}@secondary": {
                "threshold": t_sec, "rule": f"smallest threshold with VALIDATION client FPR <= {SECONDARY_VALIDATION_FPR:.1%}",
                "applied": "offline, to the logged per-request probabilities; declared now so it is not a post-hoc choice"},
        },
        "validation_counts_v7_prefix_client_level": val_cm,
        "expectation_declared_now": (
            "Revised gate R5 (one-sided 95 % upper bound on human FPR <= 1 %) with 300 humans is met only with 0 flagged "
            "humans (1 flagged gives 1.57 %). At the frozen v7 threshold the validation human FPR was 0.99 %, so a pass is "
            "not expected on EClog-like humans; the campaign humans are synthetic, so no prediction is made for them. "
            "Results are reported for every model and operating point above; none is dropped."),
        "gates": "original G1-G7 (final_campaign_config.json) for the timing shadow exactly as A/B, via the tag-pinned "
                 "evaluator; revised R1-R7 (configs/gates_revised_v1.json) for every model above with campaign_metrics.py",
        "unscored_clients": "every manifest client without a scored decision is explained from telemetry (unscored_reason)",
        "environment": {"EXTRA_SHADOW_MODEL_FILES": extra["file"], "SAGE_ML_MODE": "async",
                        "SAGE_PROBE_SECRET": "set in the shell, never recorded"},
        "hashes": files,
    }
    out = REPO / "configs" / "campaign_c_declaration_v1.json"
    out.write_text(json.dumps(decl, indent=2) + "\n")
    print(f"secondary threshold {t_sec:.6f} (frozen {d7['threshold']:.6f})")
    print("validation, frozen   :", val_cm["frozen_threshold"])
    print("validation, secondary:", val_cm["secondary_threshold"])
    print(f"wrote {rel(out)}")


if __name__ == "__main__":
    main()

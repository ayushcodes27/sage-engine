#!/usr/bin/env python3
"""
Train and freeze the two six-month EClog models of configs/offline_protocol_v1.json (B3).

  python train_eclog6m_models.py

  eclog6m_prefix_8feature_v1     prefix rows (gateway first-score vector) of train-split scored sessions
  eclog6m_completed_8feature_v1  completed-session rows of the same sessions

Uses only the train and validation splits; the test split is never loaded. The operating threshold
(smallest threshold with validation client-level FPR <= 1 %, prefix inputs) is selected here and frozen
with the model. Writes the pickles (same structure as the v6 frozen models) and
ml_pipeline/models/frozen_models_manifest_v7.json; the v6 manifest is not touched.
"""

import hashlib
import json
import pickle
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost
from xgboost import XGBClassifier

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "evaluate"))
from make_eclog6m_split import SESSIONS_6M, split_of  # noqa: E402
from offline_metrics import client_table, confusion, threshold_at_fpr  # noqa: E402

MODELS = REPO / "ml_pipeline" / "models"
CONTRACT = MODELS / "contracts" / "contract_eclog_timing_8feat.json"
PROTOCOL = REPO / "configs" / "offline_protocol_v1.json"
SPLIT = REPO / "configs" / "split_eclog6m_v1.json"
MANIFEST = MODELS / "frozen_models_manifest_v7.json"
FEATURES = json.loads(PROTOCOL.read_text())["models"]["new"]["common"]["features"]
PARAMS = dict(n_estimators=100, max_depth=6, learning_rate=0.1, random_state=42, eval_metric="logloss")
MAX_FPR = 0.01
VARIANTS = {"eclog6m_prefix_8feature_v1": "pre_", "eclog6m_completed_8feature_v1": "done_"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    df = pd.read_csv(SESSIONS_6M)
    df["split"] = df["IpId"].map(split_of(df["IpId"], SPLIT))
    df = df[(df["scored"] == 1) & (df["label"] != "unknown") & (df["split"] != "test")].copy()
    df["target"] = (df["label"] == "bot").astype(int)
    train, val = df[df["split"] == "train"], df[df["split"] == "validation"]
    contract_hash = sha256(CONTRACT)

    manifest = {
        "manifest_version": "7.0",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "New six-month EClog models (B3). The v6 frozen models and frozen_models_manifest.json are unchanged.",
        "protocol": {"path": str(PROTOCOL.relative_to(REPO)), "sha256": sha256(PROTOCOL)},
        "split": {"path": str(SPLIT.relative_to(REPO)), "sha256": sha256(SPLIT),
                  "assignment_sha256": json.loads(SPLIT.read_text())["assignment_sha256"]},
        "session_table_sha256": sha256(SESSIONS_6M),
        "training_script_sha256": sha256(__file__),
        "environment": {"python": platform.python_version(), "xgboost": xgboost.__version__,
                        "scikit-learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "contract": {"name": "eclog_timing_8feature", "path": str(CONTRACT.relative_to(REPO)), "sha256": contract_hash},
        # same recipe as inference_service/main.py (compact separators), so telemetry hashes match
        "feature_list_sha256": hashlib.sha256(json.dumps(FEATURES, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "models": {},
    }
    for name, prefix in VARIANTS.items():
        cols = [prefix + f for f in FEATURES]
        clf = XGBClassifier(**PARAMS)
        clf.fit(train[cols].values, train["target"].values)

        # threshold on validation, client level, prefix inputs (what the gateway scores)
        vprob = clf.predict_proba(val[["pre_" + f for f in FEATURES]].values)[:, 1]
        clients, n_mixed = client_table(val, vprob)
        t = threshold_at_fpr(clients.loc[clients["y"] == 0, "score"], MAX_FPR)
        cm = confusion(clients["y"], clients["score"], t)

        path = MODELS / f"{name}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": clf, "features": FEATURES, "classes": ["human", "bot"],
                         "contract_name": "eclog_timing_8feature", "contract_version": "1.0",
                         "contract_hash": contract_hash, "threshold": t, "model_version": name}, f)
        manifest["models"][name] = {
            "relative_path": str(path.relative_to(REPO)), "sha256": sha256(path), "features": FEATURES,
            "training_rows": f"{prefix}* columns of scored known-label train-split sessions",
            "train_sessions": {"bot": int(train["target"].sum()), "human": int((train["target"] == 0).sum())},
            "train_clients": int(train["IpId"].nunique()),
            "hyperparameters": PARAMS,
            "threshold": t,
            "threshold_rule": "smallest threshold with validation client-level FPR <= 1 % on prefix inputs",
            "validation_at_threshold": {"clients_bot": int(clients["y"].sum()), "clients_human": int((clients["y"] == 0).sum()),
                                        "mixed_label_clients_excluded": n_mixed, **cm},
        }
        print(name, json.dumps(manifest["models"][name]["validation_at_threshold"]), "threshold", t)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST}")


if __name__ == "__main__":
    main()

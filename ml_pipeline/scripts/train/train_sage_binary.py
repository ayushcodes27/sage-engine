"""
SAGE Engine — Binary Bot Detection Model
Classes: 0 (Human) | 1 (Bot)
Model: XGBoost
"""

import argparse
import json
import pickle
import hashlib
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
    roc_auc_score
)
from sklearn.model_selection import cross_val_score, StratifiedGroupKFold

parser = argparse.ArgumentParser(description="SAGE Engine Binary Bot Detection Model Trainer")
parser.add_argument("--data", type=str, default="ml_pipeline/data/training_data.csv")
parser.add_argument("--model-out", type=str, default="ml_pipeline/models/sage_binary_model.pkl")
parser.add_argument("--report-out", type=str, default="ml_pipeline/models/classification_report_binary.json")
parser.add_argument("--plots-prefix", type=str, default="ml_pipeline/models/sage_binary")
parser.add_argument("--contract", type=str, default="ml_pipeline/models/feature_contract.json", help="Path to contract JSON")
parser.add_argument("--threshold", type=float, default=0.50, help="Classification threshold")
parser.add_argument("--model-version", type=str, default="v1.0", help="Model version identifier")
args = parser.parse_args()

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_PATH   = Path(args.data).resolve()
MODEL_PATH  = Path(args.model_out).resolve()
REPORT_PATH = Path(args.report_out).resolve()
PLOTS_PREFIX = Path(args.plots_prefix).resolve()
CONTRACT_PATH = Path(args.contract).resolve()

MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
PLOTS_PREFIX.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_FEATURES = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio",
]
LABEL_COL = "label"

if CONTRACT_PATH.exists():
    with open(CONTRACT_PATH, "r") as f:
        contract_data = json.load(f)
    FEATURE_CONTRACT_NAME = contract_data.get("contract_name", "standard")
    FEATURE_CONTRACT_VERSION = contract_data.get("version", "1.0")
    if isinstance(contract_data.get("features"), list):
        if len(contract_data["features"]) > 0 and isinstance(contract_data["features"][0], dict):
            FEATURES = [f["name"] for f in contract_data["features"]]
        else:
            FEATURES = contract_data["features"]
    else:
        FEATURES = DEFAULT_FEATURES
    contract_bytes = open(CONTRACT_PATH, "rb").read()
    FEATURE_HASH = hashlib.sha256(contract_bytes).hexdigest()
else:
    FEATURE_CONTRACT_NAME = "unknown"
    FEATURE_CONTRACT_VERSION = "unknown"
    FEATURE_HASH = "unknown"
    FEATURES = DEFAULT_FEATURES

# ── 1. Load & clean ──────────────────────────────────────────────────────────
print("=== LOADING DATASET ===")
df = pd.read_csv(DATA_PATH)
print(f"Raw shape: {df.shape}")

# Drop fast-path dummy vectors (should be gone, but belt-and-suspenders)
dummy_mask = (
    (df["SAGE_Asset_Skip_Ratio"] == 1.0) &
    (df["SAGE_Session_Depth"]    == 0.0) &
    (df["SAGE_Request_Velocity"] == 0.0) &
    (df["SAGE_Temporal_Variance"]== 0.0)
)
dropped = dummy_mask.sum()
if dropped:
    print(f"⚠  Dropping {dropped} residual dummy vectors")
    df = df[~dummy_mask].reset_index(drop=True)

print(f"\nClean shape: {df.shape}")
print("\nOriginal Class distribution:")
print(df[LABEL_COL].value_counts())

stats = {
    "dataset_name": DATA_PATH.name,
    "raw_rows": len(df),
    "features": FEATURES,
    "unknown_count": int((df[LABEL_COL] == "unknown").sum())
}

# Filter unknown labels
df = df[df[LABEL_COL] != "unknown"].copy()

# MAP TO BINARY
df["binary_label"] = (df[LABEL_COL] != "human").astype(int)

# ── Extract client_id for leakage-free CV ─────────────────────────────────────
if "IpId" in df.columns:
    df["client_id"] = df["IpId"]
else:
    df["client_id"] = df["session_id"].str.replace(r"_sess\d+$", "", regex=True)

print("\nBinary Class distribution (0 = Human, 1 = Bot):")
print(df["binary_label"].value_counts())
print(df["binary_label"].value_counts(normalize=True).round(3))

# ── 2. Split ─────────────────────────────────────────────────────────────────
print("\n=== TRAIN / TEST SPLIT (70/30, Grouped by client_id) ===")
X = df[FEATURES]
y = df["binary_label"]
groups = df["client_id"]

clients = df["client_id"].drop_duplicates().to_numpy()
rng = np.random.default_rng(42)
rng.shuffle(clients)

split_point = int(len(clients) * 0.7)
train_clients = set(clients[:split_point])
test_clients = set(clients[split_point:])

assert train_clients.isdisjoint(test_clients)

train_mask = df["client_id"].isin(train_clients)
test_mask = df["client_id"].isin(test_clients)

X_train, X_test = X[train_mask], X[test_mask]
y_train, y_test = y[train_mask], y[test_mask]

stats["client_count"] = df["client_id"].nunique()
stats["train_clients"] = len(train_clients)
stats["test_clients"] = len(test_clients)
stats["train_rows"] = len(X_train)
stats["test_rows"] = len(X_test)

print(f"Train: {X_train.shape[0]} rows | Test: {X_test.shape[0]} rows")
print("\nTest class counts:")
print(y_test.value_counts())

# Calculate scale_pos_weight for imbalanced classes
neg_count = (y_train == 0).sum()
pos_count = (y_train == 1).sum()
scale_weight = float(neg_count) / pos_count if pos_count > 0 else 1.0

# ── 3. Train ─────────────────────────────────────────────────────────────────
print("\n=== TRAINING XGBoost (Binary) ===")
clf = XGBClassifier(
    n_estimators=150,
    max_depth=6,
    learning_rate=0.1,
    scale_pos_weight=scale_weight,
    random_state=42,
    n_jobs=-1,
    eval_metric="logloss"
)
clf.fit(X_train, y_train)
print("Training complete.")

# ── 4. Cross-validation (5-fold, stratified by group) ─────────────────────────
print("\n=== 5-FOLD CROSS-VALIDATION (F1-score) ===")
cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(clf, X, y, groups=groups, cv=cv, scoring="f1", n_jobs=-1)
print(f"Fold F1s : {np.round(cv_scores, 4)}")
print(f"Mean F1  : {cv_scores.mean():.4f}  ±  {cv_scores.std():.4f}")

# ── 5. Evaluate on holdout ───────────────────────────────────────────────────
print("\n=== HOLDOUT CLASSIFICATION REPORT ===")
y_pred = clf.predict(X_test)
y_prob = clf.predict_proba(X_test)[:, 1]

report = classification_report(y_test, y_pred, digits=3, target_names=["Human (0)", "Bot (1)"])
print(report)

report_dict = classification_report(y_test, y_pred, output_dict=True, target_names=["Human", "Bot"])
roc_auc = roc_auc_score(y_test, y_prob)
print(f"ROC-AUC Score: {roc_auc:.4f}")

# ── 6. Confusion matrix ───────────────────────────────────────────────────────
labels = [0, 1]
cm = confusion_matrix(y_test, y_pred, labels=labels)
print("Confusion matrix (rows=actual, cols=predicted):")
print(pd.DataFrame(cm, index=["Human", "Bot"], columns=["Human", "Bot"]))

fig, ax = plt.subplots(figsize=(7, 6))
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["Human", "Bot"])
disp.plot(ax=ax, colorbar=True, cmap="Blues")
ax.set_title("SAGE Binary — Confusion Matrix")
plt.tight_layout()
cm_path = PLOTS_PREFIX.parent / f"{PLOTS_PREFIX.name}_confusion_matrix.png"
plt.savefig(cm_path, dpi=150)
plt.close()
print(f"Saved -> {cm_path}")

# ── 7. Feature importance ─────────────────────────────────────────────────────
print("\n=== FEATURE IMPORTANCES ===")
importances = pd.Series(clf.feature_importances_, index=FEATURES).sort_values(ascending=False)
for feat, imp in importances.items():
    print(f"  {feat:<35} {imp:.4f}")

fig, ax = plt.subplots(figsize=(9, 5))
importances.plot(kind="bar", ax=ax, color="steelblue", edgecolor="white")
ax.set_title("SAGE Binary — Feature Importances")
ax.set_ylabel("Gain")
ax.set_xlabel("")
plt.xticks(rotation=35, ha="right")
plt.tight_layout()
fi_path = PLOTS_PREFIX.parent / f"{PLOTS_PREFIX.name}_feature_importance.png"
plt.savefig(fi_path, dpi=150)
plt.close()
print(f"Saved -> {fi_path}")

# ── 8. Persist artifacts ──────────────────────────────────────────────────────
print("\n=== SAVING ARTIFACTS ===")

def hash_file(path):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as file:
            while chunk := file.read(8192):
                h.update(chunk)
        return h.hexdigest()[:8]
    except FileNotFoundError:
        return "unknown"

model_payload = {
    "model": clf,
    "features": FEATURES,
    "classes": ["human", "bot"],
    "contract_name": FEATURE_CONTRACT_NAME,
    "contract_version": FEATURE_CONTRACT_VERSION,
    "contract_hash": FEATURE_HASH,
    "threshold": float(args.threshold),
    "model_version": args.model_version
}
with open(MODEL_PATH, "wb") as f:
    pickle.dump(model_payload, f)
print(f"Saved -> {MODEL_PATH}")

manifest_path = PLOTS_PREFIX.parent / f"{PLOTS_PREFIX.name}_split_manifest.json"
with open(manifest_path, "w") as f:
    json.dump({
        "train_clients": list(train_clients),
        "test_clients": list(test_clients)
    }, f, indent=2)
print(f"Saved -> {manifest_path}")

with open(REPORT_PATH, "w") as f:
    json.dump(
        {
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "preprocessing_hash": FEATURE_HASH,
            "dataset_hash": hash_file(DATA_PATH),
            "model_artifact_hash": hash_file(MODEL_PATH),
            "holdout_manifest_hash": hash_file(manifest_path),
            "feature_order": FEATURES,
            "classification_threshold": 0.5,
            "dataset_stats": stats,
            "cv_f1_mean": round(float(cv_scores.mean()), 4),
            "cv_f1_std":  round(float(cv_scores.std()),  4),
            "cv_fold_scores":   [round(float(s), 4) for s in cv_scores],
            "roc_auc": round(float(roc_auc), 4),
            "holdout_report":   report_dict,
            "feature_importances": {k: round(float(v), 4) for k, v in importances.items()},
        },
        f, indent=2
    )
print(f"Saved -> {REPORT_PATH}")

print("\n[SUCCESS] Binary XGBoost training complete.")

"""
evaluate_cross_dataset.py
Cross-dataset agreement with ECLog User-Agent-derived proxy labels.
"""

import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    average_precision_score,
    recall_score
)

# ── Config ───────────────────────────────────────────────────────────────────
DATA_SYNTHETIC = Path("ml_pipeline/data/training_data.csv")
DATA_ECLOG     = Path("ml_pipeline/data/eclog_weak_labeled.csv")

MODEL_SYNTHETIC = Path("ml_pipeline/models/sage_binary_model.pkl")
MODEL_ECLOG     = Path("ml_pipeline/models/eclog_weak_binary_model.pkl")

MANIFEST_ECLOG  = Path("ml_pipeline/models/eclog_weak_split_manifest.json")
REPORT_OUT      = Path("ml_pipeline/reports/cross_dataset_evaluation.json")
PLOTS_DIR       = Path("ml_pipeline/models")

THRESHOLD = 0.5

def extract_client_id(df):
    if "IpId" in df.columns:
        return df["IpId"]
    return df["session_id"].str.replace(r"_sess\d+$", "", regex=True)

def load_and_prep(path):
    df = pd.read_csv(path)
    # Drop dummies just in case
    dummy_mask = (
        (df["SAGE_Asset_Skip_Ratio"] == 1.0) &
        (df["SAGE_Session_Depth"]    == 0.0) &
        (df["SAGE_Request_Velocity"] == 0.0) &
        (df["SAGE_Temporal_Variance"]== 0.0)
    )
    if dummy_mask.sum() > 0:
        df = df[~dummy_mask].reset_index(drop=True)
    
    unknown_count = (df["label"] == "unknown").sum()
    df = df[df["label"] != "unknown"].copy()
    
    df["binary_label"] = (df["label"] != "human").astype(int)
    df["client_id"] = extract_client_id(df)
    
    return df, int(unknown_count)

def eval_model(model_data, X, y, name):
    clf = model_data["model"]
    features = model_data["features"]
    
    assert list(X.columns) == features, f"Feature mismatch for {name}: expected {features}, got {list(X.columns)}"
    
    bot_index = list(model_data["classes"]).index("bot")
    y_prob = clf.predict_proba(X)[:, bot_index]
    y_pred = (y_prob >= THRESHOLD).astype(int)
    
    roc_auc = roc_auc_score(y, y_prob)
    pr_auc = average_precision_score(y, y_prob)
    bot_recall = recall_score(y, y_pred)
    
    cm = confusion_matrix(y, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    human_fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    
    report = classification_report(y, y_pred, output_dict=True, target_names=["Human", "Bot"], zero_division=0)
    macro_f1 = report["macro avg"]["f1-score"]
    
    return {
        "roc_auc": round(float(roc_auc), 4),
        "pr_auc": round(float(pr_auc), 4),
        "macro_f1": round(float(macro_f1), 4),
        "bot_recall": round(float(bot_recall), 4),
        "human_fpr": round(float(human_fpr), 4),
        "confusion_matrix": cm.tolist()
    }, y_prob

if __name__ == "__main__":
    print("=== 1. PREPARING DATA ===")
    df_syn, syn_unk = load_and_prep(DATA_SYNTHETIC)
    df_eclog, ecl_unk = load_and_prep(DATA_ECLOG)

    with open(MANIFEST_ECLOG, "r") as f:
        manifest = json.load(f)
    test_clients = set(manifest["test_clients"])

    # Isolate ECLog holdout
    eclog_holdout = df_eclog[df_eclog["client_id"].isin(test_clients)].copy()

    print("=== 2. LOADING MODELS ===")
    with open(MODEL_SYNTHETIC, "rb") as f:
        model_syn = pickle.load(f)
    with open(MODEL_ECLOG, "rb") as f:
        model_eclog = pickle.load(f)

    # Ensure same features
    assert model_syn["features"] == model_eclog["features"], "Model feature lists do not match!"
    FEATURES = model_syn["features"]

    X_test = eclog_holdout[FEATURES]
    y_test = eclog_holdout["binary_label"]

    print("=== 3. EVALUATING ===")
    syn_metrics, syn_prob = eval_model(model_syn, X_test, y_test, "Synthetic")
    ecl_metrics, ecl_prob = eval_model(model_eclog, X_test, y_test, "ECLog Weak")

    eclog_holdout["syn_prob"] = syn_prob
    eclog_holdout["eclog_prob"] = ecl_prob

    print("\nSynthetic Model on ECLog Holdout:")
    for k, v in syn_metrics.items(): print(f"  {k}: {v}")

    print("\nECLog Model on ECLog Holdout:")
    for k, v in ecl_metrics.items(): print(f"  {k}: {v}")

    print("=== 4. PLOTTING SCORE DISTRIBUTIONS ===")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    if eclog_holdout["syn_prob"].nunique() > 1:
        sns.kdeplot(data=eclog_holdout, x="syn_prob", hue="label", fill=True, ax=ax1, common_norm=False)
    else:
        sns.histplot(data=eclog_holdout, x="syn_prob", hue="label", bins=10, ax=ax1, common_norm=False)
    ax1.set_title("Synthetic Model Score Distribution (ECLog Holdout)")
    ax1.set_xlabel("Predicted Bot Probability")

    sns.kdeplot(data=eclog_holdout, x="eclog_prob", hue="label", fill=True, ax=ax2, common_norm=False)
    ax2.set_title("ECLog Weak Model Score Distribution (ECLog Holdout)")
    ax2.set_xlabel("Predicted Bot Probability")

    plt.tight_layout()
    dist_path = PLOTS_DIR / "cross_eval_score_distributions.png"
    plt.savefig(dist_path, dpi=150)
    plt.close()
    print(f"Saved -> {dist_path}")

    print("=== 5. PLOTTING FEATURE SHIFT ===")
    fig, axes = plt.subplots(2, 4, figsize=(18, 10))
    axes = axes.flatten()

    df_syn["dataset"] = "Synthetic"
    df_eclog["dataset"] = "ECLog"
    df_combined = pd.concat([df_syn, df_eclog])

    for i, feat in enumerate(FEATURES):
        sns.boxplot(data=df_combined, x="dataset", y=feat, ax=axes[i], showfliers=False)
        axes[i].set_title(feat)
        axes[i].set_xlabel("")

    axes[7].set_visible(False)

    plt.tight_layout()
    shift_path = PLOTS_DIR / "cross_eval_feature_shift.png"
    plt.savefig(shift_path, dpi=150)
    plt.close()
    print(f"Saved -> {shift_path}")

    print("=== 6. SAVING REPORT ===")
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "metadata": {
            "interpretation": "Cross-dataset agreement with ECLog User-Agent-derived proxy labels.",
            "synthetic_model_path": str(MODEL_SYNTHETIC),
            "eclog_model_path": str(MODEL_ECLOG),
            "eclog_manifest_path": str(MANIFEST_ECLOG),
            "features": FEATURES,
            "frozen_threshold": THRESHOLD,
            "eclog_unknown_excluded": ecl_unk,
            "synthetic_unknown_excluded": syn_unk,
            "holdout_client_count": eclog_holdout["client_id"].nunique(),
            "holdout_session_count": len(eclog_holdout),
            "holdout_bot_count": int(y_test.sum()),
            "holdout_human_count": int((y_test == 0).sum())
        },
        "synthetic_model_on_eclog_holdout": syn_metrics,
        "eclog_model_on_eclog_holdout": ecl_metrics
    }

    with open(REPORT_OUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report saved to {REPORT_OUT}")

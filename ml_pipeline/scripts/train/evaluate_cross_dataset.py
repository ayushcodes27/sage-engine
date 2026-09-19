import argparse
import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    confusion_matrix,
    average_precision_score,
    f1_score
)

def parse_args():
    parser = argparse.ArgumentParser(description="Cross-evaluate models on ECLog Holdout")
    parser.add_argument("--eclog-data", default="ml_pipeline/data/eclog_weak_labeled.csv")
    parser.add_argument("--eclog-manifest", default="ml_pipeline/models/eclog_weak_split_manifest.json")
    parser.add_argument("--synth-model", default="ml_pipeline/models/sage_binary_model.pkl")
    parser.add_argument("--eclog-model", default="ml_pipeline/models/eclog_weak_binary_model.pkl")
    parser.add_argument("--output-report", default="ml_pipeline/reports/cross_evaluation.json")
    return parser.parse_args()

def evaluate_model(model_dict, X, y, model_name):
    clf = model_dict["model"]
    y_pred = clf.predict(X)
    y_prob = clf.predict_proba(X)[:, 1]
    
    report = classification_report(y, y_pred, output_dict=True, target_names=["Human", "Bot"], zero_division=0)
    roc_auc = roc_auc_score(y, y_prob)
    pr_auc = average_precision_score(y, y_prob)
    macro_f1 = f1_score(y, y_pred, average="macro")
    cm = confusion_matrix(y, y_pred, labels=[0, 1])
    
    # Calculate FPR and FNR
    tn, fp, fn, tp = cm.ravel()
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0
    
    print(f"\n=== {model_name} ===")
    print(f"ROC-AUC: {roc_auc:.4f} | PR-AUC: {pr_auc:.4f}")
    print(f"Macro F1: {macro_f1:.4f}")
    print(f"Bot Recall: {tp / (tp + fn):.2%} | Human FPR: {fpr:.2%}")
    print(f"Confusion Matrix:\n{cm}")
    
    return {
        "roc_auc": round(float(roc_auc), 4),
        "pr_auc": round(float(pr_auc), 4),
        "macro_f1": round(float(macro_f1), 4),
        "fpr": round(float(fpr), 4),
        "fnr": round(float(fnr), 4),
        "report": report,
        "confusion_matrix": cm.tolist()
    }

def main():
    args = parse_args()
    
    # Load Models
    print("Loading models...")
    with open(args.synth_model, "rb") as f:
        synth_data = pickle.load(f)
    with open(args.eclog_model, "rb") as f:
        eclog_data = pickle.load(f)
        
    # Validate feature compatibility
    synth_feats = synth_data["features"]
    eclog_feats = eclog_data["features"]
    
    if synth_feats != eclog_feats:
        raise ValueError(f"Feature mismatch between models!\nSynth: {synth_feats}\nECLog: {eclog_feats}")
        
    print(f"Feature validation passed: {len(synth_feats)} features.")
    
    # Load Manifest
    print("Loading ECLog holdout manifest...")
    with open(args.eclog_manifest, "r") as f:
        manifest = json.load(f)
    
    test_clients = set(manifest["test_clients"])
    
    # Load Data
    print("Loading ECLog data...")
    df = pd.read_csv(args.eclog_data)
    
    if "IpId" in df.columns:
        df["client_id"] = df["IpId"]
    else:
        df["client_id"] = df["session_id"].str.replace(r"_sess\d+$", "", regex=True)
        
    df = df[df["label"] != "unknown"].copy()
    df["binary_label"] = (df["label"] != "human").astype(int)
    
    # Filter for ONLY the exact holdout clients
    test_mask = df["client_id"].isin(test_clients)
    test_df = df[test_mask]
    
    X_test = test_df[synth_feats]
    y_test = test_df["binary_label"]
    
    print(f"Holdout dataset shape: {X_test.shape} (from {len(test_clients)} clients)")
    
    results = {
        "synthetic_model": evaluate_model(synth_data, X_test, y_test, "Synthetic Model on ECLog Holdout"),
        "eclog_model": evaluate_model(eclog_data, X_test, y_test, "ECLog Model on ECLog Holdout")
    }
    
    output_path = Path(args.output_report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nCross-evaluation results saved to {output_path}")

if __name__ == "__main__":
    main()

import json
import pandas as pd
import numpy as np
import argparse
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, recall_score, confusion_matrix

BASE_DIR = Path(__file__).resolve().parents[3]

ALL_FEATURES = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio"
]

def load_eclog_training_data():
    data_file = BASE_DIR / "ml_pipeline" / "data" / "eclog_weak_labeled.csv"
    df = pd.read_csv(data_file)
    df = df[df['label'] != 'unknown'].copy()
    df['target'] = (df['label'] == 'bot').astype(int)
    
    # Use frozen holdout splits
    manifest_path = BASE_DIR / "ml_pipeline" / "models" / "eclog_split_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        test_clients = set(manifest.get("test_clients", []))
    else:
        # Fallback to random if no manifest exists yet
        clients = df['IpId'].unique()
        np.random.seed(42)
        np.random.shuffle(clients)
        test_size = int(len(clients) * 0.2)
        test_clients = set(clients[:test_size])
        
    train_mask = ~df['IpId'].isin(test_clients)
    return df[train_mask]

def load_shadow_telemetry(telemetry_file):
    records = []
    with open(telemetry_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            # Only evaluate scored events
            ml = event.get("mlMetadata", {})
            if ml.get("evaluationStatus") != "Scored":
                continue
                
            if "userId" in event:
                feats = event.get("features", {})
                rec = {
                    "client_id": event.get("userId"),
                    "SAGE_Session_Depth": feats.get("sessionDepth", 0.0),
                    "SAGE_Temporal_Variance": feats.get("temporalVariance", 0.0),
                    "SAGE_Request_Velocity": feats.get("requestVelocity", 0.0),
                    "SAGE_Behavioral_Diversity": feats.get("behavioralDiversity", 0.0),
                    "SAGE_Endpoint_Concentration": feats.get("endpointConcentration", 0.0),
                    "SAGE_Cart_Ratio": feats.get("cartRatio", 0.0),
                    "SAGE_Asset_Skip_Ratio": feats.get("assetSkipRatio", 0.0)
                }
                records.append(rec)
    return pd.DataFrame(records)

def evaluate_model(y_true, y_prob, threshold=0.5):
    y_pred = (y_prob >= threshold).astype(int)
    roc_auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.0
    pr_auc = average_precision_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.0
    f1 = f1_score(y_true, y_pred, average='macro')
    bot_recall = recall_score(y_true, y_pred, pos_label=1)
    
    if len(np.unique(y_true)) > 1:
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
        human_fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    else:
        human_fpr = 0.0
        
    return {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "macro_f1": f1,
        "bot_recall": bot_recall,
        "human_fpr": human_fpr
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    # Load ground truth
    with open(args.manifest, "r") as f:
        truth_data = json.load(f)
    client_truth = truth_data["clients"]
    
    # Load and map live telemetry
    df_live = load_shadow_telemetry(args.telemetry)
    if len(df_live) == 0:
        print("No scored events found in telemetry.")
        return
        
    df_live["true_label"] = df_live["client_id"].map(client_truth)
    df_live = df_live.dropna(subset=["true_label"])
    df_live["target"] = (df_live["true_label"] == "bot").astype(int)

    # Stratify Traffic Classes (scraper, flood, human)
    def categorize_client(c_id):
        if "scraper" in c_id.lower(): return "scraper"
        if "flood" in c_id.lower(): return "flood"
        return "human"
    
    df_live["traffic_class"] = df_live["client_id"].apply(categorize_client)

    # Load training data
    df_train = load_eclog_training_data()

    ablations = [
        {"name": "Baseline (All 7)", "features": ALL_FEATURES},
        {"name": "Drop Asset_Skip_Ratio", "features": [f for f in ALL_FEATURES if f != "SAGE_Asset_Skip_Ratio"]},
        {"name": "Only Asset_Skip_Ratio", "features": ["SAGE_Asset_Skip_Ratio"]},
    ]

    print("=== Cross-Dataset Live Controlled Validation ===")
    
    for ab in ablations:
        print(f"\nTraining Model: {ab['name']}")
        features = ab["features"]
        
        clf = RandomForestClassifier(n_estimators=100, max_depth=10, min_samples_leaf=10, random_state=42)
        clf.fit(df_train[features].values, df_train["target"].values)
        
        # Score the live telemetry
        df_live[f"prob_{ab['name']}"] = clf.predict_proba(df_live[features].values)[:, 1]
        
        # Aggregate to client-level (did ANY request get flagged as > 0.5?)
        client_stats = df_live.groupby("client_id").agg({
            "target": "first",
            "traffic_class": "first",
            f"prob_{ab['name']}": "max" # max probability per client
        }).reset_index()
        
        metrics = evaluate_model(client_stats["target"].values, client_stats[f"prob_{ab['name']}"].values)
        
        print(f"ROC-AUC:   {metrics['roc_auc']:.4f}")
        print(f"PR-AUC:    {metrics['pr_auc']:.4f}")
        print(f"Macro F1:  {metrics['macro_f1']:.4f}")
        print(f"Bot Recall:{metrics['bot_recall']:.2%}")
        print(f"Human FPR: {metrics['human_fpr']:.2%}")
        
        # Stratified Breakdown
        print("  - Recall Breakdown:")
        for tc in ["scraper", "flood"]:
            tc_stats = client_stats[client_stats["traffic_class"] == tc]
            if len(tc_stats) > 0:
                recall = sum((tc_stats[f"prob_{ab['name']}"] >= 0.5).astype(int)) / len(tc_stats)
                print(f"    - {tc.capitalize()}: {recall:.2%}")
                
if __name__ == "__main__":
    main()

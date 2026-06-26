import time
import json
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    accuracy_score,
    precision_recall_fscore_support
)

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_PATH   = Path("c:/Users/deore/Desktop/Major-Project/sage-engine/ml_pipeline/data/training_data.csv")
MODEL_PATH = Path("c:/Users/deore/Desktop/Major-Project/sage-engine/ml_pipeline/models/sage_model.pkl")

FEATURES = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio",
]
LABEL_COL = "label"

def run_evaluation():
    print("=== LOADING DATASET ===")
    df = pd.read_csv(DATA_PATH)
    
    dummy_mask = (
        (df["SAGE_Asset_Skip_Ratio"] == 1.0) &
        (df["SAGE_Session_Depth"]    == 0.0) &
        (df["SAGE_Request_Velocity"] == 0.0) &
        (df["SAGE_Temporal_Variance"]== 0.0)
    )
    df = df[~dummy_mask].reset_index(drop=True)

    print("\n=== TRAIN / TEST SPLIT (70/30, Stratified by session_id) ===")
    X = df[FEATURES]
    y = df[LABEL_COL]
    
    train_idx = []
    test_idx = []

    np.random.seed(42)
    for label in df[LABEL_COL].unique():
        label_mask = df[LABEL_COL] == label
        label_sessions = df.loc[label_mask, "session_id"].unique()
        
        np.random.shuffle(label_sessions)
        split_point = int(len(label_sessions) * 0.7)
        
        if len(label_sessions) >= 2:
            split_point = max(1, min(len(label_sessions) - 1, split_point))
            
        train_sessions = label_sessions[:split_point]
        test_sessions = label_sessions[split_point:]
        
        train_idx.extend(df[label_mask & df["session_id"].isin(train_sessions)].index.tolist())
        test_idx.extend(df[label_mask & df["session_id"].isin(test_sessions)].index.tolist())

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    print("\n=== LOADING MODEL OR TRAINING IF NEEDED ===")
    if MODEL_PATH.exists():
        print(f"Loading existing model from {MODEL_PATH}")
        with open(MODEL_PATH, "rb") as f:
            model_data = pickle.load(f)
            clf = model_data["model"]
            classes = model_data["classes"]
    else:
        print("Training new model as no saved model found.")
        clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_leaf=10,
            max_features='sqrt',
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(X_train, y_train)
        classes = sorted(y.unique())

    print("\n=== METRICS (Holdout Set) ===")
    y_pred = clf.predict(X_test)
    y_prob = clf.predict_proba(X_test)
    
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Accuracy: {accuracy:.4f}")
    
    print("\n--- Classification Report ---")
    report = classification_report(y_test, y_pred, digits=4)
    print(report)
    
    print("--- Confusion Matrix ---")
    labels = clf.classes_
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    cm_df = pd.DataFrame(cm, index=labels, columns=labels)
    print(cm_df)
    
    print("\n--- ROC-AUC ---")
    try:
        roc_auc = roc_auc_score(y_test, y_prob, multi_class="ovr", average="macro")
        print(f"Macro ROC-AUC: {roc_auc:.4f}")
        # Per class ROC-AUC
        roc_auc_per_class = roc_auc_score(y_test, y_prob, multi_class="ovr", average=None)
        for cls, auc in zip(clf.classes_, roc_auc_per_class):
            print(f"  {cls}: {auc:.4f}")
    except Exception as e:
        print(f"Could not calculate ROC-AUC: {e}")

    print("\n=== K-FOLD CROSS-VALIDATION (5-Fold Stratified by Session) ===")
    from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    
    groups_full = df["session_id"]
    print("Running cross_val_predict on the full dataset...")
    y_pred_cv = cross_val_predict(clf, X, y, groups=groups_full, cv=cv, n_jobs=-1)
    
    print("\n--- CV Aggregated Classification Report ---")
    cv_report = classification_report(y, y_pred_cv, digits=4)
    print(cv_report)
    
    print("--- CV Aggregated Confusion Matrix ---")
    cm_cv = confusion_matrix(y, y_pred_cv, labels=labels)
    print(pd.DataFrame(cm_cv, index=labels, columns=labels))

    print("\n=== BOOTSTRAPPED CONFIDENCE INTERVALS (Human Recall) ===")
    from sklearn.utils import resample
    # Focus on the 'human' class using the full CV results to maximize sample size
    human_indices = np.where(y == 'human')[0]
    human_y_true = y.iloc[human_indices].values
    human_y_pred = y_pred_cv[human_indices]
    
    if len(human_indices) > 0:
        n_iterations = 1000
        bootstrapped_recalls = []
        
        for i in range(n_iterations):
            indices = resample(np.arange(len(human_y_true)), replace=True, random_state=i)
            sample_pred = human_y_pred[indices]
            # Recall = true positives / total actual positives
            recall = np.sum(sample_pred == 'human') / len(sample_pred)
            bootstrapped_recalls.append(recall)
            
        alpha = 0.95
        p = ((1.0 - alpha) / 2.0) * 100
        lower = max(0.0, np.percentile(bootstrapped_recalls, p))
        p = (alpha + ((1.0 - alpha) / 2.0)) * 100
        upper = min(1.0, np.percentile(bootstrapped_recalls, p))
        
        mean_recall = np.mean(bootstrapped_recalls)
        print(f"Human Recall (CV Aggregated): {mean_recall:.4f}")
        print(f"95% Confidence Interval: [{lower:.4f}, {upper:.4f}]")
    else:
        print("Not enough 'human' samples to bootstrap.")

    print("\n=== INFERENCE LATENCY ===")
    latencies = []
    # Test on a sample of test instances
    sample_size = min(2000, len(X_test))
    
    # We use a DataFrame to avoid UserWarnings about feature names
    test_samples_df = X_test.iloc[:sample_size]

    # For realistic single-request latency, disable joblib multiprocessing 
    # which has massive overhead for a single row prediction
    original_n_jobs = getattr(clf, "n_jobs", None)
    clf.n_jobs = 1

    # Warmup
    _ = clf.predict_proba(test_samples_df.iloc[[0]])
    
    for i in range(sample_size):
        row_df = test_samples_df.iloc[[i]]
        start_t = time.perf_counter()
        _ = clf.predict_proba(row_df)
        end_t = time.perf_counter()
        latencies.append((end_t - start_t) * 1000) # ms
        
    latencies = np.array(latencies)
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    
    # Restore n_jobs
    clf.n_jobs = original_n_jobs
    
    print(f"Total samples tested: {sample_size}")
    print(f"p50: {p50:.3f} ms")
    print(f"p95: {p95:.3f} ms")
    print(f"p99: {p99:.3f} ms")

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings('ignore') # just in case
    run_evaluation()

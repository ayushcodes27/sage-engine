"""
SAGE Engine — 10-Model Benchmark & Comparison Script
Evaluates 10 ML classifiers on SAGE 4-class bot detection dataset:
1. Random Forest (Baseline)
2. Extra Trees
3. XGBoost
4. LightGBM
5. CatBoost
6. Gradient Boosting
7. AdaBoost
8. Logistic Regression
9. SVM (RBF)
10. MLP Neural Network
"""

import time
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import (
    RandomForestClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    AdaBoostClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.metrics import (
    classification_report,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    recall_score,
)

# Optional dependencies with graceful fallback checks
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from catboost import CatBoostClassifier
    HAS_CAT = True
except ImportError:
    HAS_CAT = False

warnings.filterwarnings("ignore")

# ── Paths & Setup ────────────────────────────────────────────────────────────
DATA_PATH = Path("ml_pipeline/data/training_data.csv")
REPORT_DIR = Path("ml_pipeline/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

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

def load_data():
    print("=== LOADING & PREPARING DATASET ===")
    df = pd.read_csv(DATA_PATH)
    
    # Filter residual dummy vectors
    dummy_mask = (
        (df["SAGE_Asset_Skip_Ratio"] == 1.0) &
        (df["SAGE_Session_Depth"]    == 0.0) &
        (df["SAGE_Request_Velocity"] == 0.0) &
        (df["SAGE_Temporal_Variance"]== 0.0)
    )
    if dummy_mask.sum() > 0:
        df = df[~dummy_mask].reset_index(drop=True)
        
    df = df[df[LABEL_COL] != "unknown"].copy()
    if "IpId" in df.columns:
        df["client_id"] = df["IpId"]
    else:
        df["client_id"] = df["session_id"].str.replace(r"_sess\d+$", "", regex=True)
        
    X = df[FEATURES]
    y_raw = df[LABEL_COL]
    groups = df["client_id"]
    
    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(y_raw)
    classes = label_encoder.classes_
    human_class_idx = int(np.where(classes == "human")[0][0])
    
    # Global split by client_id (70/30)
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
    groups_train = groups[train_mask]
    
    print(f"Dataset Loaded: {len(X)} rows | Train: {len(X_train)} | Test: {len(X_test)}")
    print(f"Classes ({len(classes)}): {classes.tolist()}\n")
    
    return X, y, groups, X_train, y_train, X_test, y_test, classes, human_class_idx

def get_models(human_class_idx):
    models = {
        "Random Forest": RandomForestClassifier(
            n_estimators=100, max_depth=10, min_samples_leaf=10, max_features='sqrt',
            class_weight="balanced", random_state=42, n_jobs=-1
        ),
        "Extra Trees": ExtraTreesClassifier(
            n_estimators=100, max_depth=10, min_samples_leaf=10, max_features='sqrt',
            class_weight="balanced", random_state=42, n_jobs=-1
        ),
        "Gradient Boosting": GradientBoostingClassifier(
            n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
        ),
        "AdaBoost": AdaBoostClassifier(
            n_estimators=100, learning_rate=0.1, random_state=42
        ),
        "Logistic Regression": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42))
        ]),
        "SVM (RBF)": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", probability=True, class_weight="balanced", random_state=42))
        ]),
        "MLP Classifier": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42))
        ]),
    }
    
    if HAS_XGB:
        models["XGBoost"] = XGBClassifier(
            n_estimators=100, max_depth=6, learning_rate=0.1, random_state=42,
            n_jobs=-1, eval_metric="mlogloss"
        )
    if HAS_LGB:
        models["LightGBM"] = LGBMClassifier(
            n_estimators=100, max_depth=6, learning_rate=0.1, random_state=42,
            n_jobs=-1, class_weight="balanced", verbose=-1
        )
    if HAS_CAT:
        models["CatBoost"] = CatBoostClassifier(
            iterations=100, depth=6, learning_rate=0.1, random_seed=42,
            verbose=0, auto_class_weights="Balanced"
        )
        
    return models

def benchmark_models():
    X, y, groups, X_train, y_train, X_test, y_test, classes, human_class_idx = load_data()
    models = get_models(human_class_idx)
    
    results = []
    
    print(f"=== BENCHMARKING {len(models)} MODELS ===")
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    
    for name, model in models.items():
        print(f"--> Training & Evaluating: {name}...")
        
        # 1. 5-Fold Cross Validation F1
        cv_f1_scores = cross_val_score(
            model, X, y, groups=groups, cv=cv, scoring="f1_macro", n_jobs=-1
        )
        cv_macro_f1 = float(np.mean(cv_f1_scores))
        
        # 2. Fit model on train set
        fit_start = time.perf_counter()
        model.fit(X_train, y_train)
        fit_time_sec = time.perf_counter() - fit_start
        
        # 3. Holdout set evaluation
        y_pred = model.predict(X_test)
        holdout_macro_f1 = float(f1_score(y_test, y_pred, average="macro"))
        
        # ROC-AUC (OvR macro)
        try:
            if hasattr(model, "predict_proba"):
                y_prob = model.predict_proba(X_test)
                roc_auc = float(roc_auc_score(y_test, y_prob, multi_class="ovr", average="macro"))
            else:
                roc_auc = np.nan
        except Exception:
            roc_auc = np.nan
            
        # Human FPR (Human false positive rate = fraction of actual humans misclassified as bot)
        human_mask = (y_test == human_class_idx)
        human_preds = y_pred[human_mask]
        if len(human_preds) > 0:
            human_recall = float(np.sum(human_preds == human_class_idx) / len(human_preds))
            human_fpr = float((1.0 - human_recall) * 100) # percentage
        else:
            human_fpr = np.nan
            
        # 4. Latency measurement (p50 single-sample latency)
        latencies = []
        sample_size = min(500, len(X_test))
        X_sample = X_test.iloc[:sample_size]
        
        # Warmup
        _ = model.predict(X_sample.iloc[[0]])
        
        for i in range(sample_size):
            row = X_sample.iloc[[i]]
            t0 = time.perf_counter()
            _ = model.predict(row)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000) # ms
            
        p50_latency = float(np.median(latencies))
        p99_latency = float(np.percentile(latencies, 99))
        
        results.append({
            "Model": name,
            "CV Macro F1": round(cv_macro_f1, 4),
            "Holdout Macro F1": round(holdout_macro_f1, 4),
            "Macro ROC-AUC": round(roc_auc, 4) if not np.isnan(roc_auc) else "N/A",
            "Human FPR (%)": round(human_fpr, 2),
            "p50 Latency (ms)": round(p50_latency, 3),
            "p99 Latency (ms)": round(p99_latency, 3),
            "Fit Time (s)": round(fit_time_sec, 3),
        })
        
    df_results = pd.DataFrame(results).sort_values(by="Holdout Macro F1", ascending=False)
    
    # Save CSV
    csv_path = REPORT_DIR / "benchmark_results.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\nSaved CSV results → {csv_path}\n")
    
    # Print Table
    print(df_results.to_string(index=False))
    
    # Generate Visualizations
    generate_bar_chart(df_results)
    generate_radar_chart(df_results)
    
    print("\n✅ Model benchmarking complete!")

def generate_bar_chart(df_results):
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    models = df_results["Model"].tolist()
    x = np.arange(len(models))
    width = 0.35
    
    rects1 = ax1.bar(x - width/2, df_results["CV Macro F1"], width, label="CV Macro F1", color="#2b5c8f")
    rects2 = ax1.bar(x + width/2, df_results["Holdout Macro F1"], width, label="Holdout Macro F1", color="#46a040")
    
    ax1.set_ylabel("Macro F1 Score")
    ax1.set_title("SAGE Model Benchmark — F1 Score Comparison Across 10 Models", fontsize=14, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(models, rotation=30, ha="right")
    ax1.legend(loc="lower right")
    ax1.set_ylim(0.4, 1.0)
    ax1.grid(axis="y", linestyle="--", alpha=0.5)
    
    # Add value labels
    for rect in rects2:
        height = rect.get_height()
        ax1.annotate(f"{height:.3f}",
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=8)
                    
    plt.tight_layout()
    chart_path = REPORT_DIR / "benchmark_comparison.png"
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f"Saved Bar Chart → {chart_path}")

def generate_radar_chart(df_results):
    top_df = df_results.head(5).copy()
    
    categories = ["CV F1", "Holdout F1", "Human Precision", "Speed Score"]
    N = len(categories)
    
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]
    
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    
    max_lat = df_results["p50 Latency (ms)"].max()
    
    for _, row in top_df.iterrows():
        cv_f1 = row["CV Macro F1"]
        hold_f1 = row["Holdout Macro F1"]
        human_prec = max(0, 1.0 - (row["Human FPR (%)"] / 100.0))
        speed_score = max(0, 1.0 - (row["p50 Latency (ms)"] / (max_lat + 0.001)))
        
        values = [cv_f1, hold_f1, human_prec, speed_score]
        values += values[:1]
        
        ax.plot(angles, values, linewidth=2, linestyle='solid', label=row["Model"])
        ax.fill(angles, values, alpha=0.1)
        
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, size=10, fontweight="bold")
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"], color="grey", size=8)
    ax.set_ylim(0, 1.0)
    
    plt.title("Top 5 Models — Multi-Metric Radar Analysis", size=14, fontweight="bold", y=1.08)
    plt.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
    
    plt.tight_layout()
    radar_path = REPORT_DIR / "benchmark_radar.png"
    plt.savefig(radar_path, dpi=150)
    plt.close()
    print(f"Saved Radar Chart → {radar_path}")

if __name__ == "__main__":
    benchmark_models()

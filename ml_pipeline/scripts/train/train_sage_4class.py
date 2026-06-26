"""
SAGE Engine — 4-Class Bot Detection Model
Classes: human | flood | scraper | recon
"""

import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
)
from sklearn.model_selection import cross_val_score, StratifiedGroupKFold
from sklearn.preprocessing import LabelEncoder

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_PATH   = Path("ml_pipeline/data/training_data.csv")
OUTPUT_DIR  = Path("ml_pipeline/models")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
print("\nClass distribution:")
print(df[LABEL_COL].value_counts())
print(df[LABEL_COL].value_counts(normalize=True).round(3))

# ── 2. Split ─────────────────────────────────────────────────────────────────
print("\n=== TRAIN / TEST SPLIT (70/30, Stratified by session_id) ===")
X = df[FEATURES]
y = df[LABEL_COL]
groups = df["session_id"]

train_idx = []
test_idx = []

np.random.seed(42)
for label in df[LABEL_COL].unique():
    label_mask = df[LABEL_COL] == label
    label_sessions = df.loc[label_mask, "session_id"].unique()
    
    np.random.shuffle(label_sessions)
    split_point = int(len(label_sessions) * 0.7)
    
    # Ensure at least 1 session in test if possible
    if len(label_sessions) >= 2:
        split_point = max(1, min(len(label_sessions) - 1, split_point))
        
    train_sessions = label_sessions[:split_point]
    test_sessions = label_sessions[split_point:]
    
    train_idx.extend(df[label_mask & df["session_id"].isin(train_sessions)].index.tolist())
    test_idx.extend(df[label_mask & df["session_id"].isin(test_sessions)].index.tolist())

X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

print(f"Train: {X_train.shape[0]} rows | Test: {X_test.shape[0]} rows")
print("\nTest class counts:")
print(y_test.value_counts())

# ── 3. Train ─────────────────────────────────────────────────────────────────
print("\n=== TRAINING RandomForest (4-class, balanced weights) ===")
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
print("Training complete.")

# ── 4. Cross-validation (5-fold, stratified by group) ─────────────────────────
print("\n=== 5-FOLD CROSS-VALIDATION (macro F1) ===")
cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(clf, X, y, groups=groups, cv=cv, scoring="f1_macro", n_jobs=-1)
print(f"Fold F1s : {np.round(cv_scores, 4)}")
print(f"Mean F1  : {cv_scores.mean():.4f}  ±  {cv_scores.std():.4f}")

# ── 5. Zero-Day Bot CV (Leave-One-Bot-Out) ───────────────────────────────────
print("\n=== ZERO-DAY BOT DETECTION (Leave-One-Bot-Out) ===")
bot_classes = [c for c in df[LABEL_COL].unique() if c != "human"]
zero_day_results = {}

for held_out_bot in bot_classes:
    train_mask = df[LABEL_COL] != held_out_bot
    X_train_zd = df.loc[train_mask, FEATURES]
    y_train_zd = df.loc[train_mask, LABEL_COL]
    
    if len(X_train_zd) == 0:
        print(f"Skipping zero-day evaluation for {held_out_bot} because no training data remains.")
        continue
    
    clf_zd = RandomForestClassifier(
        n_estimators=100, max_depth=10, min_samples_leaf=10, max_features='sqrt',
        class_weight="balanced", random_state=42, n_jobs=-1
    )
    clf_zd.fit(X_train_zd, y_train_zd)
    
    test_mask = df[LABEL_COL] == held_out_bot
    X_test_zd = df.loc[test_mask, FEATURES]
    
    if len(X_test_zd) == 0:
        continue
        
    y_pred_zd = clf_zd.predict(X_test_zd)
    detected_as_bot = (y_pred_zd != "human").sum()
    total = len(y_pred_zd)
    recall = detected_as_bot / total
    
    zero_day_results[held_out_bot] = round(recall, 4)
    print(f"Held out {held_out_bot:<10} | Detected as Bot: {detected_as_bot}/{total} ({recall:.1%})")

# ── 6. Evaluate on holdout ───────────────────────────────────────────────────
print("\n=== HOLDOUT CLASSIFICATION REPORT ===")
y_pred = clf.predict(X_test)
report = classification_report(y_test, y_pred, digits=3)
print(report)

report_dict = classification_report(y_test, y_pred, output_dict=True)

# ── 7. Confusion matrix ───────────────────────────────────────────────────────
labels = sorted(y.unique())
cm = confusion_matrix(y_test, y_pred, labels=labels)
print("Confusion matrix (rows=actual, cols=predicted):")
print(pd.DataFrame(cm, index=labels, columns=labels))

fig, ax = plt.subplots(figsize=(7, 6))
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
disp.plot(ax=ax, colorbar=True, cmap="Blues")
ax.set_title("SAGE 4-Class — Confusion Matrix")
plt.tight_layout()
cm_path = OUTPUT_DIR / "confusion_matrix.png"
plt.savefig(cm_path, dpi=150)
plt.close()
print(f"Saved → {cm_path}")

# ── 8. Feature importance ─────────────────────────────────────────────────────
print("\n=== FEATURE IMPORTANCES ===")
importances = pd.Series(clf.feature_importances_, index=FEATURES).sort_values(ascending=False)
for feat, imp in importances.items():
    print(f"  {feat:<35} {imp:.4f}")

fig, ax = plt.subplots(figsize=(9, 5))
importances.plot(kind="bar", ax=ax, color="steelblue", edgecolor="white")
ax.set_title("SAGE 4-Class — Feature Importances")
ax.set_ylabel("Mean Decrease in Impurity")
ax.set_xlabel("")
plt.xticks(rotation=35, ha="right")
plt.tight_layout()
fi_path = OUTPUT_DIR / "feature_importance.png"
plt.savefig(fi_path, dpi=150)
plt.close()
print(f"Saved → {fi_path}")

# ── 9. Persist artifacts ──────────────────────────────────────────────────────
print("\n=== SAVING ARTIFACTS ===")

model_path = OUTPUT_DIR / "sage_model.pkl"
with open(model_path, "wb") as f:
    pickle.dump({"model": clf, "features": FEATURES, "classes": labels}, f)
print(f"Saved → {model_path}")

report_path = OUTPUT_DIR / "classification_report.json"
with open(report_path, "w") as f:
    json.dump(
        {
            "cv_macro_f1_mean": round(float(cv_scores.mean()), 4),
            "cv_macro_f1_std":  round(float(cv_scores.std()),  4),
            "cv_fold_scores":   [round(float(s), 4) for s in cv_scores],
            "zero_day_bot_recall": zero_day_results,
            "holdout_report":   report_dict,
            "feature_importances": {k: round(float(v), 4) for k, v in importances.items()},
        },
        f, indent=2
    )
print(f"Saved → {report_path}")

print("\n✅ 4-class training complete.")

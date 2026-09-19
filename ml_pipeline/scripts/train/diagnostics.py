import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import learning_curve, StratifiedGroupKFold
from sklearn.metrics import f1_score
import os

def load_and_clean_data(csv_path="ml_pipeline/data/training_data.csv"):
    df = pd.read_csv(csv_path)
    
    # Drop rows with NaN
    df = df.dropna()
    df = df[df["label"] != "unknown"].copy()

    FEATURES = [
        "SAGE_Session_Depth",
        "SAGE_Temporal_Variance",
        "SAGE_Request_Velocity",
        "SAGE_Behavioral_Diversity",
        "SAGE_Endpoint_Concentration",
        "SAGE_Cart_Ratio",
        "SAGE_Asset_Skip_Ratio",
    ]
    X = df[FEATURES]
    y = df["label"]
    if "IpId" in df.columns:
        df["client_id"] = df["IpId"]
    else:
        df["client_id"] = df["session_id"].str.replace(r"_sess\d+$", "", regex=True)
    groups = df["client_id"]
    return X, y, groups

def plot_learning_curve(X, y, groups):
    print("=== RUNNING LEARNING CURVE DIAGNOSTIC ===")
    
    rf = RandomForestClassifier(
        n_estimators=100, max_depth=10, min_samples_leaf=10, max_features='sqrt',
        class_weight='balanced', random_state=42, n_jobs=-1
    )
    
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    
    train_sizes, train_scores, test_scores = learning_curve(
        rf, X, y, groups=groups, cv=cv, scoring='f1_macro',
        train_sizes=np.array([0.1, 0.25, 0.5, 0.75, 1.0]),
        n_jobs=-1
    )
    
    train_mean = np.mean(train_scores, axis=1)
    train_std = np.std(train_scores, axis=1)
    test_mean = np.mean(test_scores, axis=1)
    test_std = np.std(test_scores, axis=1)
    
    plt.figure(figsize=(10, 6))
    plt.plot(train_sizes, train_mean, 'o-', color="r", label="Training F1 Score")
    plt.fill_between(train_sizes, train_mean - train_std, train_mean + train_std, alpha=0.1, color="r")
    
    plt.plot(train_sizes, test_mean, 'o-', color="g", label="Validation F1 Score")
    plt.fill_between(train_sizes, test_mean - test_std, test_mean + test_std, alpha=0.1, color="g")
    
    plt.title("Learning Curve (Random Forest)")
    plt.xlabel("Training Examples")
    plt.ylabel("Macro F1 Score")
    plt.legend(loc="best")
    plt.grid(True)
    
    out_path = "ml_pipeline/models/learning_curve.png"
    plt.savefig(out_path)
    print(f"Saved Learning Curve plot to {out_path}\n")

def run_noise_degradation_test(X, y, groups):
    print("=== RUNNING NOISE DEGRADATION TEST ===")
    
    train_idx = []
    test_idx = []
    import numpy as np
    import pandas as pd
    
    df = pd.DataFrame({"label": y, "client_id": groups})
    
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
    
    rf = RandomForestClassifier(
        n_estimators=100, max_depth=10, min_samples_leaf=10, max_features='sqrt',
        class_weight='balanced', random_state=42, n_jobs=-1
    )
    rf.fit(X_train, y_train)
    
    # Baseline
    y_pred_baseline = rf.predict(X_test)
    baseline_f1 = f1_score(y_test, y_pred_baseline, average='macro')
    print(f"Baseline F1 (0% Noise): {baseline_f1:.4f}")
    
    noise_levels = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]
    f1_scores = []
    
    # Calculate feature std dev for realistic proportional noise scaling
    feature_stds = X_test.std(axis=0)
    
    for level in noise_levels:
        if level == 0.0:
            f1_scores.append(baseline_f1)
            continue
            
        # Add Gaussian noise proportional to each feature's standard deviation
        noise = np.random.normal(0, level, X_test.shape) * feature_stds.values
        X_test_noisy = X_test + noise
        
        # Ensure values don't go strictly negative if they are strictly positive counts/ratios
        X_test_noisy = np.maximum(X_test_noisy, 0)
        
        y_pred = rf.predict(X_test_noisy)
        score = f1_score(y_test, y_pred, average='macro')
        f1_scores.append(score)
        print(f"Noise {int(level*100)}% -> F1: {score:.4f}")
        
    plt.figure(figsize=(10, 6))
    plt.plot([l * 100 for l in noise_levels], f1_scores, 'b-o', linewidth=2)
    plt.title("Model Robustness: F1 Score vs Gaussian Noise")
    plt.xlabel("Gaussian Noise Added to Test Set (%)")
    plt.ylabel("Macro F1 Score")
    plt.grid(True)
    
    # Highlight the safe degradation zone
    plt.axhline(y=baseline_f1, color='r', linestyle='--', alpha=0.5, label="Baseline")
    
    out_path = "ml_pipeline/models/noise_degradation.png"
    plt.savefig(out_path)
    print(f"\nSaved Noise Degradation plot to {out_path}")

if __name__ == "__main__":
    os.makedirs("ml_pipeline/models", exist_ok=True)
    X, y, groups = load_and_clean_data()
    plot_learning_curve(X, y, groups)
    run_noise_degradation_test(X, y, groups)
    print("\n✅ Diagnostics complete.")

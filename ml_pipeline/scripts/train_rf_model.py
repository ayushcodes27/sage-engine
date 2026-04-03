# ml_pipeline/scripts/train_rf_model.py
import pandas as pd
import joblib
import json
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, roc_auc_score, confusion_matrix
from sklearn.model_selection import train_test_split

# Configuration

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)

DATA_FILE = os.path.join(BASE_DIR, "data", "sage_training_data.csv")
INFERENCE_DIR = os.path.join(BASE_DIR, "inference_service")
MODEL_DIR = os.path.join(INFERENCE_DIR, "models")

MODEL_FILE = os.path.join(MODEL_DIR, "sage_rf_model_v1.joblib")
FEATURES_FILE = os.path.join(MODEL_DIR, "sage_rf_features.joblib")
REPORT_FILE = os.path.join(INFERENCE_DIR, "evaluation_report.json")

FEATURES = ['endpoint_diversity', 'temporal_variance', 'session_depth', 'request_velocity']

def train_sage_model():
    print(f"Loading data from {DATA_FILE}...")
    df = pd.read_csv(DATA_FILE)

    # Random Forest uses BOTH humans and bots to learn the difference
    X = df[FEATURES]
    y = df['label'] # 0 = Human, 1 = Bot

    # Split into 80% training, 20% testing
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    # Scale Features
    print("Scaling features...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train the Random Forest
    print("Training Random Forest Classifier on Application-Layer Features...")
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    model.fit(X_train_scaled, y_train)


    # Evaluation

    print("\nEvaluating against test data...")
    predictions = model.predict(X_test_scaled)
    probabilities = model.predict_proba(X_test_scaled)[:, 1] # Probability of being a bot

    # Metrics
    roc_auc = roc_auc_score(y_test, probabilities)
    cm = confusion_matrix(y_test, predictions)
    report = classification_report(y_test, predictions, target_names=['Human', 'Bot'], output_dict=True)

    print("\n--- SAGE Random Forest Evaluation ---")
    print(f"ROC-AUC Score: {roc_auc:.4f}")
    print(f"Precision (Bot): {report['Bot']['precision']:.4f}")
    print(f"Recall (Bot): {report['Bot']['recall']:.4f}")
    print(f"F1-Score (Bot): {report['Bot']['f1-score']:.4f}")
    print("\nConfusion Matrix (Test Set):")
    print(f"True Humans: {cm[0][0]} | False Bots (FP): {cm[0][1]}")
    print(f"False Humans (FN): {cm[1][0]} | True Bots: {cm[1][1]}")

    # SAVe
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(model, MODEL_FILE)
    joblib.dump(
        [
            "SAGE_Session_Depth",
            "SAGE_Temporal_Variance",
            "SAGE_Request_Velocity",
            "SAGE_Behavioral_Diversity",
        ],
        FEATURES_FILE,
    )

    report_data = {
        "algorithm": "RandomForestClassifier",
        "roc_auc": roc_auc,
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "features_used": FEATURES
    }
    with open(REPORT_FILE, 'w') as f:
        json.dump(report_data, f, indent=4)

    print(f"\nArtifacts saved to '{MODEL_DIR}/'")

if __name__ == "__main__":
    train_sage_model()

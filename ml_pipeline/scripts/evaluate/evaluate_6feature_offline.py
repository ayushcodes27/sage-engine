import argparse
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

BASE_DIR = Path(__file__).resolve().parents[2]
SIX_FEATURES = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
]

TELEMETRY_FEATURE_MAP = {
    "SAGE_Session_Depth": "sessionDepth",
    "SAGE_Temporal_Variance": "temporalVariance",
    "SAGE_Request_Velocity": "requestVelocity",
    "SAGE_Behavioral_Diversity": "behavioralDiversity",
    "SAGE_Endpoint_Concentration": "endpointConcentration",
    "SAGE_Cart_Ratio": "cartRatio",
}

PROFILE_ORDER = [
    "normal_browser",
    "spa_client",
    "mobile_browser",
    "privacy_browser",
    "slow_scraper",
    "asset_fetching_bot",
    "fast_scraper",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate 6-feature (drop-Asset_Skip_Ratio) model offline on telemetry.")
    parser.add_argument("--telemetry", required=True, help="Path to telemetry JSONL")
    parser.add_argument("--manifest", required=True, help="Path to shadow manifest JSON")
    parser.add_argument("--model", default=str(BASE_DIR / "models" / "eclog_6feature_binary_model.pkl"), help="Path to 6-feature model pkl")
    parser.add_argument("--data", default=str(BASE_DIR / "data" / "eclog_weak_labeled.csv"), help="Training data if model needs building")
    parser.add_argument("--split-manifest", default=str(BASE_DIR / "models" / "eclog_weak_split_manifest.json"))
    parser.add_argument("--threshold", type=float, default=0.50, help="Classification threshold")
    parser.add_argument("--report", help="Optional markdown output path")
    return parser.parse_args()


def get_or_train_6feature_model(model_path: Path, data_path: Path, split_manifest_path: Path):
    if model_path.exists():
        with open(model_path, "rb") as f:
            data = pickle.load(f)
        print(f"[+] Loaded existing 6-feature model from {model_path}")
        return data["model"]

    print(f"[*] Training 6-feature model (dropping SAGE_Asset_Skip_Ratio) from {data_path}...")
    df = pd.read_csv(data_path)
    df = df[df["label"] != "unknown"].copy()
    df["binary_label"] = (df["label"] != "human").astype(int)

    if "IpId" in df.columns:
        df["client_id"] = df["IpId"]
    else:
        df["client_id"] = df["session_id"].str.replace(r"_sess\d+$", "", regex=True)

    if split_manifest_path.exists():
        with open(split_manifest_path, "r") as f:
            manifest = json.load(f)
        train_clients = set(manifest.get("train_clients", []))
    else:
        clients = df["client_id"].drop_duplicates().to_numpy()
        rng = np.random.default_rng(42)
        rng.shuffle(clients)
        train_clients = set(clients[: int(len(clients) * 0.7)])

    train_mask = df["client_id"].isin(train_clients)
    X_train = df.loc[train_mask, SIX_FEATURES]
    y_train = df.loc[train_mask, "binary_label"]

    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_weight = float(neg_count) / pos_count if pos_count > 0 else 1.0

    clf = XGBClassifier(
        n_estimators=150,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale_weight,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
    )
    clf.fit(X_train, y_train)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump({"model": clf, "features": SIX_FEATURES, "classes": [0, 1]}, f)
    print(f"[+] Saved 6-feature model to {model_path}")
    return clf


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    clients = {}
    for client_id, value in manifest.get("clients", {}).items():
        if isinstance(value, str):
            clients[client_id] = {
                "client_id": client_id,
                "profile": "unknown",
                "expected_label": value,
                "true_class": value,
            }
        else:
            clients[client_id] = {
                "client_id": value.get("client_id", client_id),
                "profile": value.get("profile", "unknown"),
                "expected_label": value.get("expected_label", value.get("true_class")),
                "true_class": value.get("true_class", value.get("expected_label")),
            }
    return manifest, clients


def pct(val):
    return f"{val * 100:.2f}%"


def evaluate_6feature(telemetry_path, manifest_path, model_path, data_path, split_manifest_path, threshold):
    manifest, client_manifest = load_manifest(manifest_path)
    run_id = manifest.get("run_id")
    clf = get_or_train_6feature_model(Path(model_path), Path(data_path), Path(split_manifest_path))

    records = []
    with open(telemetry_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("schemaVersion") != "1.1" or event.get("runId") != run_id:
                continue

            features = event.get("features") or {}
            ml = event.get("mlMetadata") or {}
            client_id = event.get("userId")

            if client_id not in client_manifest:
                continue

            # Check if all 6 features are available
            vector = []
            valid = True
            for feat_name in SIX_FEATURES:
                field_key = TELEMETRY_FEATURE_MAP[feat_name]
                if field_key not in features or features[field_key] is None:
                    valid = False
                    break
                vector.append(float(features[field_key]))

            if not valid:
                continue

            records.append({
                "event_id": event.get("eventId"),
                "client_id": client_id,
                "eval_status": ml.get("evaluationStatus"),
                "7feat_shadow_prob": ml.get("shadowBotProbability"),
                "vector": vector,
            })

    if not records:
        return "No valid telemetry records found with compatible feature vectors."

    df_records = pd.DataFrame(records)
    # Perform 6-feature inference
    X_input = pd.DataFrame(df_records["vector"].tolist(), columns=SIX_FEATURES)
    probs_6f = clf.predict_proba(X_input)[:, 1]
    df_records["6feat_prob"] = probs_6f

    # Map manifest metadata
    manifest_df = pd.DataFrame(client_manifest.values())
    merged = df_records.merge(manifest_df, on="client_id", how="left")

    # Group by client - evaluate using the scoring request (or max prob)
    # The moment evaluation was done in 7-feat model: eval_status == "Scored"
    scored_only = merged[merged["eval_status"] == "Scored"].copy()
    if len(scored_only) == 0:
        scored_only = merged.copy()

    client_summary = scored_only.groupby("client_id").agg(
        profile=("profile", "first"),
        true_class=("true_class", "first"),
        prob_7f=("7feat_shadow_prob", "first"),
        prob_6f=("6feat_prob", "first"),
    ).reset_index()

    lines = []
    lines.append("# Six-Feature (Drop-Asset-Skip) Model Offline Evaluation")
    lines.append("")
    lines.append(f"Run ID: `{run_id}`")
    lines.append("Evaluates the ECLog weak model without `SAGE_Asset_Skip_Ratio` against recorded telemetry feature vectors.")
    lines.append("")

    lines.append("## Overall Metrics Comparison (Threshold = 0.50)")
    lines.append("")
    lines.append("| Metric | 7-Feature (Production Baseline) | 6-Feature (Drop Asset-Skip) | Delta |")
    lines.append("|---|---:|---:|---:|")

    for th in [0.50, 0.35]:
        pred_7f = client_summary["prob_7f"].fillna(0) >= th
        pred_6f = client_summary["prob_6f"] >= th

        bots = client_summary["true_class"] == "bot"
        humans = client_summary["true_class"] == "human"

        rec_7f = (pred_7f & bots).sum() / bots.sum() if bots.sum() > 0 else 0.0
        rec_6f = (pred_6f & bots).sum() / bots.sum() if bots.sum() > 0 else 0.0

        fpr_7f = (pred_7f & humans).sum() / humans.sum() if humans.sum() > 0 else 0.0
        fpr_6f = (pred_6f & humans).sum() / humans.sum() if humans.sum() > 0 else 0.0

        lines.append(f"| **Bot Recall (th={th:.2f})** | {pct(rec_7f)} | {pct(rec_6f)} | {pct(rec_6f - rec_7f)} |")
        lines.append(f"| **Human FPR (th={th:.2f})** | {pct(fpr_7f)} | {pct(fpr_6f)} | {pct(fpr_6f - fpr_7f)} |")

    lines.append("")
    lines.append("## Profile-by-Profile Detailed Comparison")
    lines.append("")
    lines.append("| Profile | Class | Clients | 7-Feat Avg Prob | 6-Feat Avg Prob | 7-Feat Result (th=0.50) | 6-Feat Result (th=0.50) | 6-Feat Result (th=0.35) |")
    lines.append("|---|---|---:|---:|---:|---|---|---|")

    for profile in PROFILE_ORDER:
        pdf = client_summary[client_summary["profile"] == profile]
        if len(pdf) == 0:
            continue
        c_class = pdf["true_class"].iloc[0]
        avg_7f = pdf["prob_7f"].mean()
        avg_6f = pdf["prob_6f"].mean()

        if c_class == "bot":
            res_7f = f"Recall {pct((pdf['prob_7f'] >= 0.50).mean())}"
            res_6f = f"Recall {pct((pdf['prob_6f'] >= 0.50).mean())}"
            res_6f_35 = f"Recall {pct((pdf['prob_6f'] >= 0.35).mean())}"
        else:
            res_7f = f"FPR {pct((pdf['prob_7f'] >= 0.50).mean())}"
            res_6f = f"FPR {pct((pdf['prob_6f'] >= 0.50).mean())}"
            res_6f_35 = f"FPR {pct((pdf['prob_6f'] >= 0.35).mean())}"

        lines.append(f"| {profile} | {c_class} | {len(pdf)} | {avg_7f:.4f} | {avg_6f:.4f} | {res_7f} | {res_6f} | {res_6f_35} |")

    return "\n".join(lines)


def main():
    args = parse_args()
    report = evaluate_6feature(
        args.telemetry,
        args.manifest,
        args.model,
        args.data,
        args.split_manifest,
        args.threshold,
    )
    print(report)
    if args.report:
        out_path = Path(args.report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()

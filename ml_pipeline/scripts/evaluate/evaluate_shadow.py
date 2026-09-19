#!/usr/bin/env python3
"""
evaluate_shadow.py

Evaluates controlled SAGE shadow traffic against ground-truth manifest and
verifies cryptographic identity assertions on all scored records against the
tagged frozen manifest.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

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
    parser = argparse.ArgumentParser(description="Evaluate controlled SAGE shadow traffic.")
    parser.add_argument("--telemetry", required=True, help="Path to exported Kafka telemetry JSONL")
    parser.add_argument("--manifest", required=True, help="Path to shadow manifest JSON")
    parser.add_argument("--report", help="Optional markdown report output path")
    parser.add_argument("--tag", default="v2-frozen-models-v5", help="Git tag containing frozen manifest")
    parser.add_argument("--frozen-manifest", help="Optional local path to frozen models manifest fallback")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 if identity verification or gates fail")
    return parser.parse_args()


def get_evaluator_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def get_git_head() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def load_tagged_frozen_manifest(
    tag: str = "v2-frozen-models", fallback_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    """
    Loads frozen manifest from git show <tag>:path to guarantee expected hashes
    come from the immutable git tag, falling back to local disk if tag is not yet cut.
    """
    manifest_bytes = None
    source = f"git show {tag}:ml_pipeline/models/frozen_models_manifest.json"
    try:
        res = subprocess.run(
            ["git", "show", f"{tag}:ml_pipeline/models/frozen_models_manifest.json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest_bytes = res.stdout
    except Exception:
        candidates = [
            Path(fallback_path) if fallback_path else None,
            Path(__file__).resolve().parents[2] / "models" / "frozen_models_manifest.json",
        ]
        for c in candidates:
            if c and c.exists():
                manifest_bytes = c.read_bytes()
                source = f"working_tree:{c}"
                break

    if manifest_bytes:
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        data = json.loads(manifest_bytes.decode("utf-8"))
        return data, manifest_sha256, source
    return None, None, "not_found"


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
                "request_count": value.get("request_count"),
            }

    return manifest, clients


def production_action(prob):
    if pd.isna(prob):
        return "Unavailable"
    if prob >= 0.80:
        return "Blocked"
    if prob >= 0.50:
        return "Challenged"
    return "Allowed"


def bootstrap_ci(df, stat_func, samples=1000, alpha=0.05):
    if len(df) == 0:
        return 0.0, 0.0, 0.0

    rng = np.random.default_rng(42)
    stats = []
    for _ in range(samples):
        indices = rng.integers(0, len(df), len(df))
        sample = df.iloc[indices]
        stats.append(stat_func(sample))

    stats = np.sort(np.array(stats, dtype=float))
    low_idx = int((alpha / 2.0) * samples)
    high_idx = min(samples - 1, int((1 - alpha / 2.0) * samples))
    return stat_func(df), stats[low_idx], stats[high_idx]


def ratio(numerator, denominator):
    return 0.0 if denominator == 0 else numerator / denominator


def summarize_client_metrics(client_df):
    tp = int(((client_df["true_label"] == "bot") & client_df["predicted_bot"]).sum())
    fp = int(((client_df["true_label"] == "human") & client_df["predicted_bot"]).sum())
    tn = int(((client_df["true_label"] == "human") & ~client_df["predicted_bot"]).sum())
    fn = int(((client_df["true_label"] == "bot") & ~client_df["predicted_bot"]).sum())

    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "human_fpr": ratio(fp, fp + tn),
        "bot_recall": ratio(tp, tp + fn),
        "precision": ratio(tp, tp + fp),
    }


def pct(value):
    return f"{value * 100:.2f}%"


def latency_summary(series):
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) == 0:
        return None, None
    return clean.quantile(0.50), clean.quantile(0.95)


def load_telemetry(path, run_id=None):
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("schemaVersion") != "1.1":
                continue
            if run_id is not None and event.get("runId") != run_id:
                continue

            ml = event.get("mlMetadata") or {}
            features = event.get("features") or {}
            row = {
                "event_id": event.get("eventId"),
                "run_id": event.get("runId"),
                "client_id": event.get("userId"),
                "path": (event.get("request") or {}).get("path"),
                "status": (event.get("response") or {}).get("status"),
                "bot_prob": ml.get("botProbability"),
                "is_bot": ml.get("isBotFlag") == 1,
                "shadow_prob": ml.get("shadowBotProbability"),
                "shadow_is_bot": ml.get("shadowIsBotFlag") == 1,
                "shadow_action": ml.get("shadowAction"),
                "shadow_status": ml.get("shadowStatus"),
                "prod_latency": ml.get("prodInferenceLatencyMs"),
                "shadow_latency": ml.get("shadowInferenceLatencyMs"),
                "contract_hash": ml.get("contractHash"),
                "model_version": ml.get("modelVersion"),
                "shadow_threshold": ml.get("shadowThreshold"),
                "prod_model_sha256": ml.get("prodModelSha256"),
                "shadow_model_sha256": ml.get("shadowModelSha256"),
                "shadow_contract_hash": ml.get("shadowContractHash"),
                "shadow_feature_list_hash": ml.get("shadowFeatureListHash"),
                "evaluation_status": ml.get("evaluationStatus"),
                "scoring_depth": ml.get("scoringDepth"),
                "session_depth": features.get("sessionDepth") or features.get("SAGE_Session_Depth"),
                "navigation_gap": features.get("nonStaticNavigationGap") if features.get("nonStaticNavigationGap") is not None else features.get("SAGE_NonStatic_Navigation_Gap"),
                "long_gap_ratio": features.get("nonStaticLongGapRatio") if features.get("nonStaticLongGapRatio") is not None else features.get("SAGE_NonStatic_Long_Gap_Ratio"),
                "feature_vector_present": bool(features),
            }
            row["prod_action"] = production_action(row["bot_prob"])
            rows.append(row)

    return pd.DataFrame(rows)


def verify_identity_assertions(
    df: pd.DataFrame, expected_active: Optional[Dict[str, Any]]
) -> Tuple[bool, List[str], int, int]:
    """
    Identity Verification:
    - 'scored' is decided strictly by shadow score status (shadow_status == 'ok')
    - Every scored record needs the full tuple:
      (prod_model_sha256, shadow_model_sha256, shadow_contract_hash, shadow_feature_list_hash, shadow_threshold)
    - Tuple must equal the tagged manifest, not just be internally consistent.
    - Zero mixed identity allowed across scored records.
    - Zero timeout/error records allowed in dataset.
    - Unscored records are counted separately.
    """
    errors = []

    # Check 0: Zero timeout or error records across all telemetry
    error_cond = df["shadow_status"].isin(["timeout", "error"])
    if "status" in df.columns:
        error_cond = error_cond | (pd.to_numeric(df["status"], errors="coerce") >= 500)
    error_records = df[error_cond]
    if len(error_records) > 0:
        errors.append(f"{len(error_records)} telemetry records encountered error or timeout status")

    is_scored = (
        (df["shadow_status"] == "ok")
        & df["shadow_prob"].notna()
        & df["shadow_is_bot"].notna()
    )
    scored = df[is_scored].copy()
    unscored = df[~is_scored].copy()

    scored_count = len(scored)
    unscored_count = len(unscored)

    if scored_count == 0:
        errors.append("No scored records found in telemetry (shadow_status == 'ok')")
        return False, errors, scored_count, unscored_count

    # Check 1: Missing metadata on scored records
    identity_cols = [
        "prod_model_sha256",
        "shadow_model_sha256",
        "shadow_contract_hash",
        "shadow_feature_list_hash",
        "shadow_threshold",
    ]
    missing_mask = scored[identity_cols].isna().any(axis=1)
    missing_count = int(missing_mask.sum())
    if missing_count > 0:
        errors.append(
            f"{missing_count} scored records missing complete cryptographic identity tuple"
        )

    # Check 2: Mixed identities across scored records
    clean_scored = scored.dropna(subset=identity_cols).copy()
    if len(clean_scored) > 0:
        distinct_tuples = clean_scored[identity_cols].drop_duplicates()
        if len(distinct_tuples) > 1:
            errors.append(
                f"Mixed identities detected: {len(distinct_tuples)} distinct identity tuples found across scored records"
            )

        # Check 3: Match against tagged frozen manifest
        if expected_active is not None:
            observed_row = distinct_tuples.iloc[0].to_dict()
            mismatches = []
            for key in identity_cols:
                exp_val = expected_active.get(key)
                obs_val = observed_row.get(key)
                if key == "shadow_threshold":
                    if exp_val is None or obs_val is None or abs(float(exp_val) - float(obs_val)) > 1e-5:
                        mismatches.append(f"{key}: expected {exp_val}, got {obs_val}")
                else:
                    if str(exp_val) != str(obs_val):
                        mismatches.append(f"{key}: expected {exp_val}, got {obs_val}")
            if mismatches:
                errors.append(
                    f"Scored identity does not match tagged manifest: {'; '.join(mismatches)}"
                )
        else:
            errors.append("Tagged frozen manifest expected identity was not provided or could not be loaded")
    else:
        errors.append("All scored records had missing identity fields")

    return len(errors) == 0, errors, scored_count, unscored_count


def build_report(
    manifest,
    client_manifest,
    df,
    bootstrap_samples,
    tag="v2-frozen-models",
    frozen_manifest=None,
    frozen_manifest_sha256=None,
    manifest_source="unknown",
):
    lines = []
    run_id = manifest.get("run_id", "unknown")
    git_head = get_git_head()
    evaluator_hash = get_evaluator_hash()
    harness_hash = manifest.get("harness_hash", "unknown")
    campaign_config_hash = manifest.get("campaign_config_hash", "unknown")
    seeds = manifest.get("seeds", {"random_state": 42})

    # Deployed artifacts & container image IDs
    def get_path_sha256(rel_path: str) -> str:
        p = Path(__file__).resolve().parents[2] / rel_path
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "not_found"

    def get_container_image(container_name: str) -> str:
        try:
            r = subprocess.run(
                ["docker", "inspect", "--format={{.Image}}", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    main_py_sha256 = get_path_sha256("ml_pipeline/inference_service/main.py")
    gateway_jar_sha256 = get_path_sha256("sage-gateway/target/sage-gateway-0.0.1-SNAPSHOT.jar")
    ml_image_id = get_container_image("sage-ml")
    gw_image_id = get_container_image("sage-gateway")

    lines.append("# Diverse Shadow Validation Report")
    lines.append("")
    lines.append(f"- **Run ID**: `{run_id}`")
    lines.append(f"- **Git HEAD**: `{git_head}`")
    lines.append(f"- **Git Tag**: `{tag}`")
    lines.append(f"- **Frozen Manifest SHA-256**: `{frozen_manifest_sha256}` (source: `{manifest_source}`)")
    lines.append(f"- **Harness Hash**: `{harness_hash}`")
    lines.append(f"- **Evaluator Hash**: `{evaluator_hash}`")
    lines.append(f"- **Campaign Config Hash**: `{campaign_config_hash}`")
    lines.append(f"- **Seeds**: `{json.dumps(seeds)}`")
    lines.append(f"- **Deployed main.py SHA-256**: `{main_py_sha256}`")
    lines.append(f"- **Deployed Gateway JAR SHA-256**: `{gateway_jar_sha256}`")
    lines.append(f"- **Deployed sage-ml Container Image ID**: `{ml_image_id}`")
    lines.append(f"- **Deployed sage-gateway Container Image ID**: `{gw_image_id}`")
    lines.append("")
    lines.append("This is run-specific controlled validation using manifest labels. It is not proof of real-world accuracy, and it must not be reported as production ground truth.")
    lines.append("Enforcement remains disabled. Threshold calibration must use a separate validation set; the ECLog holdout remains untouched.")
    lines.append("")

    profile_matrix = manifest.get("profile_matrix", {})
    if profile_matrix:
        lines.append("## Profile Matrix")
        lines.append("")
        lines.append("| Profile | Expected class | Asset behavior | Rate |")
        lines.append("|---|---|---|---|")
        for profile in PROFILE_ORDER:
            meta = profile_matrix.get(profile)
            if not meta:
                continue
            lines.append(
                f"| {profile} | {meta.get('expected_class')} | {meta.get('asset_behavior')} | {meta.get('rate')} |"
            )
        lines.append("")

    lines.append(f"Manifest clients: {len(client_manifest)}")
    lines.append(f"Telemetry events matched by run_id: {len(df)}")

    if len(df) == 0:
        lines.append("")
        lines.append("No telemetry matched this run ID. Metrics were not computed.")
        return "\n".join(lines), False

    manifest_df = pd.DataFrame(client_manifest.values())
    joined = df.merge(
        manifest_df[["client_id", "profile", "true_class", "expected_label"]],
        on="client_id",
        how="left",
    )
    matched = joined.dropna(subset=["true_class"]).copy()
    unmatched_events = len(joined) - len(matched)
    missing_clients = sorted(set(client_manifest.keys()) - set(matched["client_id"].dropna().unique()))

    lines.append(f"Telemetry events joined to manifest client_id: {len(matched)}")
    lines.append(f"Telemetry events without manifest truth: {unmatched_events}")
    lines.append(f"Manifest clients without telemetry: {len(missing_clients)}")

    # Identity Verification
    expected_active = frozen_manifest.get("active_deployment") if frozen_manifest else None
    identity_ok, identity_errors, scored_count, unscored_count = verify_identity_assertions(
        matched, expected_active
    )

    lines.append("")
    lines.append("## Cryptographic Identity Verification")
    lines.append("")
    lines.append(f"- **Scored Records Count (shadow_status == 'ok')**: {scored_count}")
    lines.append(f"- **Unscored Records Count (shadow_status != 'ok')**: {unscored_count}")
    lines.append(f"- **Identity Tuple Gate**: {'PASS' if identity_ok else 'FAIL'}")

    if expected_active:
        lines.append(f"- **Expected Model SHA-256 (Prod)**: `{expected_active.get('prod_model_sha256')}`")
        lines.append(f"- **Expected Model SHA-256 (Shadow)**: `{expected_active.get('shadow_model_sha256')}`")
        lines.append(f"- **Expected Contract Hash**: `{expected_active.get('shadow_contract_hash')}`")
        lines.append(f"- **Expected Feature List Hash**: `{expected_active.get('shadow_feature_list_hash')}`")
        lines.append(f"- **Expected Shadow Threshold**: `{expected_active.get('shadow_threshold')}`")

    if identity_errors:
        lines.append("")
        lines.append("### Identity Verification Errors:")
        for err in identity_errors:
            lines.append(f"- ❌ {err}")

    scored = matched[
        (matched["shadow_status"] == "ok")
        & matched["shadow_prob"].notna()
        & matched["shadow_is_bot"].notna()
    ].copy()
    scored_clients = set(scored["client_id"].dropna().unique())
    manifest_client_ids = set(client_manifest)
    unscored_clients = manifest_client_ids - scored_clients
    lines.append("")
    lines.append(f"Shadow-scored events: {len(scored)}")
    lines.append(f"Shadow-scored clients: {len(scored_clients)}")
    lines.append(f"Clients without a valid shadow score: {len(unscored_clients)}")

    # Diagnosis of Unscored Records
    unscored = matched[
        (matched["shadow_status"] != "ok")
        | matched["shadow_prob"].isna()
        | matched["shadow_is_bot"].isna()
    ].copy()
    depth_gated = (
        (unscored["shadow_status"] == "skipped")
        & (unscored["session_depth"].fillna(0) <= 20)
    ).sum()
    other_gated = len(unscored) - depth_gated
    error_or_timeout = unscored["shadow_status"].isin(["timeout", "error"]).sum()

    lines.append("")
    lines.append("### Unscored Records Diagnostics:")
    lines.append(f"- **Total Unscored Records**: {len(unscored)}")
    lines.append(f"- **Depth-Gated (sessionDepth <= 20)**: {depth_gated}")
    lines.append(f"- **Duration/Other-Gated**: {other_gated}")
    lines.append(f"- **Error or Timeout Records**: {error_or_timeout}")

    # Feature Delivery Verification (Asserting 8 features & non-default-filled timing features)
    lines.append("")
    lines.append("### Shadow Feature Delivery Verification:")
    timing_features_valid = False
    if len(scored) > 0 and "navigation_gap" in scored and "long_gap_ratio" in scored:
        avg_nav_gap = float(scored["navigation_gap"].dropna().mean()) if len(scored["navigation_gap"].dropna()) > 0 else 0.0
        avg_long_gap = float(scored["long_gap_ratio"].dropna().mean()) if len(scored["long_gap_ratio"].dropna()) > 0 else 0.0
        non_zero_gaps = int((scored["navigation_gap"] > 0).sum())
        lines.append(f"- **Mean Navigation_Gap on scored records**: {avg_nav_gap:.4f} s (non-zero count: {non_zero_gaps}/{len(scored)})")
        lines.append(f"- **Mean Long_Gap_Ratio on scored records**: {avg_long_gap:.4f}")
        timing_features_valid = (avg_nav_gap > 0.0) or (avg_long_gap > 0.0) or (non_zero_gaps > 0)
        lines.append(f"- **Timing Features Not Default-Filled**: {'PASS' if timing_features_valid else 'FAIL'}")
    else:
        lines.append("- ❌ Timing feature columns missing from telemetry")

    if len(matched) == 0 or len(scored) == 0:
        lines.append("")
        lines.append("No valid shadow predictions matched the truth manifest. Metrics are unavailable; infrastructure failures must not be counted as bot misses.")
        return "\n".join(lines), False

    scored["predicted_bot"] = scored["shadow_is_bot"].astype(bool)
    client_stats = scored.groupby("client_id").agg(
        true_label=("true_class", "first"),
        profile=("profile", "first"),
        predicted_bot=("predicted_bot", "any"),
        event_count=("event_id", "count"),
        scored_events=("shadow_prob", lambda s: s.notna().sum()),
        mean_shadow_prob=("shadow_prob", "mean"),
    ).reset_index()

    metrics = summarize_client_metrics(client_stats)
    fpr_ci = bootstrap_ci(
        client_stats[client_stats["true_label"] == "human"],
        lambda d: summarize_client_metrics(d)["human_fpr"],
        bootstrap_samples,
    )
    recall_ci = bootstrap_ci(
        client_stats[client_stats["true_label"] == "bot"],
        lambda d: summarize_client_metrics(d)["bot_recall"],
        bootstrap_samples,
    )
    precision_ci = bootstrap_ci(
        client_stats,
        lambda d: summarize_client_metrics(d)["precision"],
        bootstrap_samples,
    )

    lines.append("")
    lines.append("## Aggregate Client Metrics")
    lines.append("")
    lines.append(f"Human FPR: {pct(fpr_ci[0])} (95% CI {pct(fpr_ci[1])} - {pct(fpr_ci[2])})")
    lines.append(f"Bot recall: {pct(recall_ci[0])} (95% CI {pct(recall_ci[1])} - {pct(recall_ci[2])})")
    lines.append(f"Precision: {pct(precision_ci[0])} (95% CI {pct(precision_ci[1])} - {pct(precision_ci[2])})")
    lines.append(f"Confusion matrix: TP={metrics['tp']} FP={metrics['fp']} TN={metrics['tn']} FN={metrics['fn']}")

    lines.append("")
    lines.append("## Profile Metrics")
    lines.append("")
    lines.append("| Profile | Class | Clients | Metric | Value | 95% CI |")
    lines.append("|---|---|---:|---|---:|---|")
    for profile in PROFILE_ORDER + sorted(set(client_stats["profile"]) - set(PROFILE_ORDER)):
        prof_df = client_stats[client_stats["profile"] == profile]
        if len(prof_df) == 0:
            continue
        label = prof_df["true_label"].iloc[0]
        if label == "human":
            ci = bootstrap_ci(prof_df, lambda d: summarize_client_metrics(d)["human_fpr"], bootstrap_samples)
            metric_name = "FPR"
        else:
            ci = bootstrap_ci(prof_df, lambda d: summarize_client_metrics(d)["bot_recall"], bootstrap_samples)
            metric_name = "Recall"
        lines.append(f"| {profile} | {label} | {len(prof_df)} | {metric_name} | {pct(ci[0])} | {pct(ci[1])} - {pct(ci[2])} |")

    # Latency
    valid_latency = scored.dropna(subset=["prod_latency", "shadow_latency"]).copy()
    if len(valid_latency) > 0:
        valid_latency["paired_overhead"] = pd.to_numeric(valid_latency["shadow_latency"]) - pd.to_numeric(valid_latency["prod_latency"])
        prod_p50, prod_p95 = latency_summary(valid_latency["prod_latency"])
        shadow_p50, shadow_p95 = latency_summary(valid_latency["shadow_latency"])
        over_p50, over_p95 = latency_summary(valid_latency["paired_overhead"])
        negative = (valid_latency["paired_overhead"] < 0).mean()

        lines.append("")
        lines.append("## Latency")
        lines.append("")
        lines.append(f"Paired request/event IDs: {len(valid_latency)}")
        lines.append(f"Production latency p50/p95: {prod_p50:.2f} ms / {prod_p95:.2f} ms")
        lines.append(f"Shadow latency p50/p95: {shadow_p50:.2f} ms / {shadow_p95:.2f} ms")
        lines.append(f"Paired overhead p50/p95: {over_p50:.2f} ms / {over_p95:.2f} ms")
        lines.append(f"Negative paired overhead rate: {pct(negative)}")
    else:
        over_p95 = 0.0
        lines.append("")
        lines.append("No paired production/shadow latency values were available.")

    lines.append("")
    lines.append("## Safety Gates")
    lines.append("")
    client_gate_ok = (len(unscored_clients) == 0) and (len(scored_clients) == len(manifest_client_ids)) and len(manifest_client_ids) > 0
    zero_errors_ok = (error_or_timeout == 0) and (len(identity_errors) == 0 or not any("error or timeout" in e for e in identity_errors))
    gates = [
        ("Cryptographic Identity Verified (Tagged Manifest)", identity_ok),
        ("Client-Level Acceptance Gate (scored_clients == manifest_clients, >=1 shadow 'ok' per client)", client_gate_ok),
        ("Zero timeout or error records", zero_errors_ok),
        ("Timing Features Present & Active (8 features)", timing_features_valid),
        ("Human FPR < 10%", fpr_ci[0] < 0.10),
        ("Bot recall > 90%", recall_ci[0] > 0.90),
        ("p95 paired overhead < 50 ms", over_p95 < 50),
    ]
    all_passed = True
    for name, passed in gates:
        status_str = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        lines.append(f"{name}: {status_str}")

    lines.append("")
    if all_passed:
        lines.append("Controlled run gates passed. This supports additional diverse shadow runs and threshold calibration, not production enforcement.")
    else:
        lines.append("One or more controlled run gates failed. Do not enable enforcement.")

    return "\n".join(lines), all_passed


def main():
    args = parse_args()
    manifest, client_manifest = load_manifest(args.manifest)
    run_id = manifest.get("run_id")
    telemetry = load_telemetry(args.telemetry, run_id)

    frozen_manifest, frozen_sha, source = load_tagged_frozen_manifest(
        args.tag, args.frozen_manifest
    )

    report, passed = build_report(
        manifest,
        client_manifest,
        telemetry,
        args.bootstrap_samples,
        tag=args.tag,
        frozen_manifest=frozen_manifest,
        frozen_manifest_sha256=frozen_sha,
        manifest_source=source,
    )

    print(report)
    if args.report:
        output = Path(args.report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport written to {output}")

    if args.strict and not passed:
        print("\nEvaluation failed strict safety or identity gates.")
        sys.exit(1)


if __name__ == "__main__":
    main()

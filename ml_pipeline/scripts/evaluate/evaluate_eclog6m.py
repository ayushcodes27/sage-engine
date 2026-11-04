#!/usr/bin/env python3
"""
Six-month EClog evaluation (B3) exactly as declared in configs/offline_protocol_v1.json and v1_1.json.

  python evaluate_eclog6m.py [--out results/offline/eclog6m_evaluation.json] [--bootstrap 2000]

v1   : frozen v6 models (sage_binary_model @0.5, eclog_timing_binary_model @0.35) and the v7 models
       (eclog6m_prefix_8feature_v1, eclog6m_completed_8feature_v1) on the TEST split, prefix inputs
       (primary) and completed inputs (secondary); client level (primary) and session level; thresholds
       fixed / validation-selected (FPR <= 1 %, <= 5 %) / test-ROC descriptive; ROC-AUC, PR-AUC, Brier with
       client-cluster bootstrap CIs; reliability curve; coverage at k in {5, 10, 15, 21}; test recall by
       crawler fold.
v1.1 : leave-one-crawler-family-out retraining of the prefix model.
The Markov baseline (v1) needs session path sequences and is produced by a separate script.
"""

import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "evaluate"))
from campaign_metrics import clopper_pearson  # noqa: E402
from make_eclog6m_split import SESSIONS_6M, split_of  # noqa: E402
from offline_metrics import client_table, confusion, threshold_at_fpr  # noqa: E402

MODELS = REPO / "ml_pipeline" / "models"
FAMILY_CSV = REPO / "ml_pipeline" / "data" / "eclog6m_bot_family.csv"
P1 = REPO / "configs" / "offline_protocol_v1.json"
P11 = REPO / "configs" / "offline_protocol_v1_1.json"
EVAL_MODELS = {
    "sage_binary_model": ("sage_binary_model.pkl", 0.5),
    "eclog_timing_binary_model": ("eclog_timing_binary_model.pkl", 0.35),
    "eclog6m_prefix_8feature_v1": ("eclog6m_prefix_8feature_v1.pkl", None),
    "eclog6m_completed_8feature_v1": ("eclog6m_completed_8feature_v1.pkl", None),
}
SEED = 42


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_model(fname):
    d = pickle.loads((MODELS / fname).read_bytes())
    return d, sha256(MODELS / fname)


def proba(d, df, prefix):
    return d["model"].predict_proba(df[[prefix + f for f in d["features"]]].values)[:, 1]


def rates(cm):
    return {**cm,
            "recall": clopper_pearson(cm["tp"], cm["tp"] + cm["fn"]),
            "fpr": clopper_pearson(cm["fp"], cm["fp"] + cm["tn"]),
            "precision": clopper_pearson(cm["tp"], cm["tp"] + cm["fp"])}


def boot_ci(stat, n, reps, rng):
    vals = []
    for _ in range(reps):
        v = stat(rng.integers(0, n, n))
        if v is not None:
            vals.append(v)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if vals else None


def auc_block(y, s, reps, rng):
    y, s = np.asarray(y), np.asarray(s)

    def stat(f):
        def g(i):
            return f(y[i], s[i]) if 0 < y[i].sum() < len(i) else None
        return g
    return {"roc_auc": float(roc_auc_score(y, s)), "roc_auc_ci95": boot_ci(stat(roc_auc_score), len(y), reps, rng),
            "pr_auc": float(average_precision_score(y, s)),
            "pr_auc_ci95": boot_ci(stat(average_precision_score), len(y), reps, rng)}


def brier_block(sessions, prob, reps, rng):
    y = (sessions["label"].values == "bot").astype(float)
    sq = (np.asarray(prob) - y) ** 2
    codes, uniq = pd.factorize(sessions["IpId"].values)
    sums, counts = np.bincount(codes, sq), np.bincount(codes)

    def stat(i):
        return float(sums[i].sum() / counts[i].sum())
    return {"brier": float(sq.mean()), "brier_ci95_client_bootstrap": boot_ci(stat, len(uniq), reps, rng)}


def reliability(sessions, prob):
    y = (sessions["label"].values == "bot").astype(int)
    p = np.asarray(prob)
    b = np.minimum((p * 10).astype(int), 9)
    return [{"bin": f"[{i / 10:.1f},{(i + 1) / 10:.1f}{']' if i == 9 else ')'}", "n": int((b == i).sum()),
             "mean_predicted": float(p[b == i].mean()) if (b == i).any() else None,
             "observed_bot_rate": float(y[b == i].mean()) if (b == i).any() else None} for i in range(10)]


def fold_of(family, folds):
    for name, fams in folds.items():
        if isinstance(fams, list) and family in fams:
            return name
    return "other"


def evaluate_model(d, thr_fixed, val, test, prefix, reps, rng, client_fold):
    vprob, tprob = proba(d, val, prefix), proba(d, test, prefix)
    vc, vmixed = client_table(val, vprob)
    tc, tmixed = client_table(test, tprob)
    vh = vc.loc[vc["y"] == 0, "score"]
    th = tc.loc[tc["y"] == 0, "score"]
    thresholds = {"validation_fpr_le_1pct": threshold_at_fpr(vh, 0.01), "validation_fpr_le_5pct": threshold_at_fpr(vh, 0.05)}
    if thr_fixed is not None:
        thresholds["fixed"] = thr_fixed
    if d.get("threshold") is not None and thr_fixed is None:
        thresholds["frozen_v7"] = d["threshold"]
    ops = {k: rates(confusion(tc["y"], tc["score"], t)) | {"threshold": t} for k, t in thresholds.items()}
    for k in ("validation_fpr_le_1pct", "fixed"):
        if k in ops:
            t = thresholds[k]
            bots = tc[tc["y"] == 1].assign(fold=lambda x: x["IpId"].map(client_fold).fillna("untagged"))
            ops[k]["test_recall_by_crawler_fold"] = {
                f: clopper_pearson(int((g["score"] >= t).sum()), len(g)) for f, g in bots.groupby("fold")}
    descriptive = {}
    for fpr in (0.01, 0.05):
        t = threshold_at_fpr(th, fpr)
        descriptive[f"test_fpr_le_{int(fpr * 100)}pct"] = rates(confusion(tc["y"], tc["score"], t)) | {"threshold": t}
    sess = test.assign(y=(test["label"] == "bot").astype(int))
    return {
        "client_level": {"n_bot": int(tc["y"].sum()), "n_human": int((tc["y"] == 0).sum()),
                         "mixed_label_clients_excluded": tmixed, "validation_mixed_excluded": vmixed,
                         **auc_block(tc["y"], tc["score"], reps, rng),
                         "operating_points": ops, "descriptive_test_roc_points": descriptive},
        "session_level": {"n_bot": int(sess["y"].sum()), "n_human": int((sess["y"] == 0).sum()),
                          "roc_auc": float(roc_auc_score(sess["y"], tprob)),
                          "pr_auc": float(average_precision_score(sess["y"], tprob)),
                          **brier_block(test, tprob, reps, rng), "reliability_10_bins": reliability(test, tprob)},
    }


def coverage(all_sessions, splits):
    known = all_sessions[all_sessions["label"] != "unknown"]
    out = {}
    for name, df in [("all", known)] + [(s, known[known["split"] == s]) for s in splits]:
        out[name] = {}
        for lab, g in df.groupby("label"):
            row = {}
            for k in (5, 10, 15, 21):
                reach = (g["n_non_static"] >= k) & (g["duration_s"] >= 3.0)
                cl = g.assign(r=reach).groupby("IpId")["r"].any()
                row[f"k{k}"] = {"sessions": clopper_pearson(int(reach.sum()), len(g)),
                                "clients": clopper_pearson(int(cl.sum()), len(cl))}
            out[name][lab] = row
    return out


def lofo(train, val, test_humans_sessions, all_scored, client_fold, folds, features, reps, rng, ref_models):
    out = {}
    params = dict(n_estimators=100, max_depth=6, learning_rate=0.1, random_state=42, eval_metric="logloss")
    prefixed = ["pre_" + f for f in features]
    for fold in list(folds) + (["other"] if "other" not in folds else []):
        held_clients = {ip for ip, f in client_fold.items() if f == fold}
        tr = train[~((train["label"] == "bot") & train["IpId"].isin(held_clients))]
        clf = XGBClassifier(**params).fit(tr[prefixed].values, (tr["label"] == "bot").astype(int).values)
        vprob = clf.predict_proba(val[prefixed].values)[:, 1]
        vc, _ = client_table(val, vprob)
        t = threshold_at_fpr(vc.loc[vc["y"] == 0, "score"], 0.01)
        held = all_scored[(all_scored["label"] == "bot") & all_scored["IpId"].isin(held_clients)]
        hc, _ = client_table(held, clf.predict_proba(held[prefixed].values)[:, 1])
        thc, _ = client_table(test_humans_sessions, clf.predict_proba(test_humans_sessions[prefixed].values)[:, 1])
        both = pd.concat([hc, thc])
        res = {"held_out_bot_clients": len(hc), "held_out_bot_clients_by_split":
               held.drop_duplicates("IpId")["split"].value_counts().to_dict(),
               "train_bot_sessions": int((tr["label"] == "bot").sum()), "threshold": t,
               "held_out_recall": clopper_pearson(int((hc["score"] >= t).sum()), len(hc)),
               "test_human_fpr": clopper_pearson(int((thc["score"] >= t).sum()), len(thc)),
               **{k: v for k, v in auc_block(both["y"], both["score"], reps, rng).items() if k.startswith("roc")}}
        # references
        d7, thr7 = ref_models["eclog6m_prefix_8feature_v1"]
        ht = held[held["split"] == "test"]
        if len(ht):
            c7, _ = client_table(ht, proba(d7, ht, "pre_"))
            res["reference_v7_prefix_recall_on_fold_test_clients"] = clopper_pearson(int((c7["score"] >= thr7).sum()), len(c7))
        d6, thr6 = ref_models["eclog_timing_binary_model"]
        hvt = held[held["split"].isin(["validation", "test"])]
        if len(hvt):
            c6, _ = client_table(hvt, proba(d6, hvt, "pre_"))
            res["reference_frozen_timing_recall_on_fold_val_test_clients"] = clopper_pearson(int((c6["score"] >= thr6).sum()), len(c6))
        out[fold] = res
        print(f"  LOFO {fold}: held-out recall {res['held_out_recall']['point']:.3f} "
              f"({res['held_out_recall']['k']}/{res['held_out_recall']['n']}), test human FPR {res['test_human_fpr']['point']:.4f}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "results" / "offline" / "eclog6m_evaluation.json"))
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    sessions = pd.read_csv(SESSIONS_6M)
    sessions["split"] = sessions["IpId"].map(split_of(sessions["IpId"]))
    fam = pd.read_csv(FAMILY_CSV)
    folds = json.loads(P11.read_text())["folds"]
    client_fold = {ip: fold_of(f, folds) for ip, f in zip(fam["IpId"], fam["family"])}

    scored = sessions[(sessions["scored"] == 1) & (sessions["label"] != "unknown")]
    train, val, test = (scored[scored["split"] == s] for s in ("train", "validation", "test"))

    report = {"protocols": {"v1": {"path": str(P1.relative_to(REPO)), "sha256": sha256(P1)},
                            "v1_1": {"path": str(P11.relative_to(REPO)), "sha256": sha256(P11)}},
              "inputs": {"session_table_sha256": sha256(SESSIONS_6M), "bot_family_csv_sha256": sha256(FAMILY_CSV),
                         "evaluator_sha256": sha256(__file__), "bootstrap_resamples": args.bootstrap, "seed": SEED},
              "models": {}, "coverage": coverage(sessions, ["train", "validation", "test"])}
    ref = {}
    for name, (fname, thr) in EVAL_MODELS.items():
        d, h = load_model(fname)
        ref[name] = (d, thr if thr is not None else d["threshold"])
        report["models"][name] = {"sha256": h, "features": d["features"], "inputs": {}}
        for inp, prefix in (("prefix", "pre_"), ("completed", "done_")):
            report["models"][name]["inputs"][inp] = evaluate_model(d, thr, val, test, prefix, args.bootstrap, rng, client_fold)
            cl = report["models"][name]["inputs"][inp]["client_level"]
            print(f"{name:32s} {inp:9s} client AUC {cl['roc_auc']:.4f}")
    features = json.loads(P1.read_text())["models"]["new"]["common"]["features"]
    report["leave_one_family_out"] = lofo(train, val, test[test["label"] == "human"], scored, client_fold, folds,
                                          features, args.bootstrap, rng, ref)
    tagged = scored[scored["label"] == "bot"].drop_duplicates("IpId").merge(fam, on="IpId", how="left")
    report["family_tagging"] = {"scored_bot_clients": len(tagged), "untagged": int(tagged["family"].isna().sum()),
                                "purity_below_0_9": int((tagged["purity"] < 0.9).sum()),
                                "clients_per_fold": tagged["IpId"].map(client_fold).fillna("untagged").value_counts().to_dict()}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

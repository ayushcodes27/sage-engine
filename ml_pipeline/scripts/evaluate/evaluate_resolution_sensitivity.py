#!/usr/bin/env python3
"""
Timestamp-resolution sensitivity (audit N1), exactly as declared in configs/offline_protocol_v1_2_resolution.json.

  python evaluate_resolution_sensitivity.py [--out results/offline/eclog6m_resolution_sensitivity.json]

Streams eclog.zip, and for every test-split scored known-label session recomputes the gateway's first-score prefix
vector under the control (u = 0) and 5 sub-second jitter draws. The control must reproduce the session table's
pre_* columns, else the run aborts. Cached in ml_pipeline/data/eclog6m_resolution_features.jsonl.gz.
"""

import argparse
import csv
import gzip
import hashlib
import json
import multiprocessing as mp
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "evaluate"))
import build_eclog_sessions as B  # noqa: E402
from evaluate_eclog6m import MODELS, EVAL_MODELS, rates, sha256  # noqa: E402
from gateway_emulator import FEATURES, SESSION_GAP_S, first_score  # noqa: E402
from make_eclog6m_split import SESSIONS_6M, split_of  # noqa: E402
from offline_metrics import client_table, confusion  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

DATA = REPO / "ml_pipeline" / "data"
CACHE = DATA / "eclog6m_resolution_features.jsonl.gz"
PROTOCOL = REPO / "configs" / "offline_protocol_v1_2_resolution.json"
SEEDS = [42, 43, 44, 45, 46]
WANTED = set()


def jitter(ticks, seed, ip, s_idx):
    h = int.from_bytes(hashlib.blake2b(f"{ip}/{s_idx}".encode(), digest_size=8).digest(), "big")
    u = np.random.default_rng([seed, h]).random(len(ticks))
    ticks = np.asarray(ticks)
    return u[np.lexsort((u, ticks))]  # ticks are already non-decreasing; ascending draws within equal-timestamp runs


def vector(times, uris):
    fs = first_score(list(times), uris)
    return None if fs is None else [fs[3][c] for c in FEATURES]


def bucket_features(args):
    path, out_path = args
    rows = []
    with open(path, newline="") as f:
        for ip, ticks, rowno, uri, code in csv.reader(f, delimiter="\t"):
            rows.append((ip, int(ticks), int(rowno), uri, code))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    n = 0
    with gzip.open(out_path, "wt") as out:
        i = 0
        while i < len(rows):
            j = i
            while j < len(rows) and rows[j][0] == rows[i][0]:
                j += 1
            client, s_idx, start = rows[i:j], 0, 0
            for k in range(1, len(client) + 1):
                if k == len(client) or (client[k][1] - client[k - 1][1]) / B.TICKS_PER_S > SESSION_GAP_S:
                    ip = client[0][0]
                    if (ip, s_idx) in WANTED:
                        sess = client[start:k]
                        t = np.array([r[1] / B.TICKS_PER_S for r in sess])
                        uris = [r[3] for r in sess]
                        res = [vector(t, uris)] + [vector(t + jitter([r[1] for r in sess], sd, ip, s_idx), uris)
                                                   for sd in SEEDS]
                        out.write(json.dumps([ip, s_idx, res]) + "\n")
                        n += 1
                    s_idx += 1
                    start = k
            i = j
    return n


def extract(wanted):
    WANTED.update(wanted)
    tmp = DATA / "eclog6m_resolution.buckets"
    t0 = time.time()
    B.partition(DATA / "eclog.zip", tmp, 64)
    parts = [(tmp / f"b{i:03d}.tsv", tmp / f"r{i:03d}.jsonl.gz") for i in range(64)]
    with mp.Pool(max(1, (mp.cpu_count() or 2) - 2)) as pool:
        total = sum(pool.imap_unordered(bucket_features, parts))
    if total != len(WANTED):
        raise RuntimeError(f"extracted {total} sessions, expected {len(WANTED)}")
    with open(CACHE, "wb") as f:
        for _, q in sorted(parts):
            f.write(q.read_bytes())
    for b, q in parts:
        b.unlink()
        q.unlink()
    tmp.rmdir()
    print(f"recomputed {total:,} sessions x 6 variants in {time.time() - t0:.0f} s", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "results" / "offline" / "eclog6m_resolution_sensitivity.json"))
    args = ap.parse_args()

    sessions = pd.read_csv(SESSIONS_6M)
    sessions["split"] = sessions["IpId"].map(split_of(sessions["IpId"]))
    test = sessions[(sessions["scored"] == 1) & (sessions["label"] != "unknown") & (sessions["split"] == "test")]
    test = test.reset_index(drop=True)
    if not CACHE.exists():
        extract(set(zip(test["IpId"], test["session_idx"])))
    feats = {}
    with gzip.open(CACHE, "rt") as f:
        for ip, s, res in map(json.loads, f):
            feats[(ip, s)] = res
    variants = [[feats[(ip, s)][v] for ip, s in zip(test["IpId"], test["session_idx"])] for v in range(6)]

    # control must reproduce the session table
    ctrl = np.array([np.nan if v is None else v for v in variants[0]], dtype=object)
    if any(v is None for v in variants[0]):
        raise SystemExit("control lost a scored session")
    ctrl_m = np.array(variants[0], dtype=float)
    table = test[["pre_" + c for c in FEATURES]].values.astype(float)
    if not np.allclose(ctrl_m, table, rtol=1e-6, atol=1e-9):
        raise SystemExit(f"control does not reproduce pre_* columns (max abs diff {np.abs(ctrl_m - table).max()})")
    print("control reproduces the session table's pre_* columns")

    report = {"protocol": {"path": str(PROTOCOL.relative_to(REPO)), "sha256": sha256(PROTOCOL)},
              "inputs": {"session_table_sha256": sha256(SESSIONS_6M), "features_cache_sha256": sha256(CACHE),
                         "script_sha256": sha256(__file__), "seeds": SEEDS, "test_scored_sessions": len(test)},
              "feature_shift": {}, "dropped_sessions_per_draw": [], "models": {}}
    keep = [np.array([v is not None for v in variants[d]]) for d in range(1, 6)]
    report["dropped_sessions_per_draw"] = [int((~k).sum()) for k in keep]

    gap = FEATURES.index("SAGE_NonStatic_Navigation_Gap")
    for fi, name in enumerate(FEATURES):
        shares = []
        for d in range(5):
            k = keep[d]
            p = np.array([v[fi] for v, ok in zip(variants[d + 1], k) if ok], dtype=float)
            c = ctrl_m[k, fi]
            if name == "SAGE_NonStatic_Navigation_Gap":
                changed = (p < 0.5) != (c < 0.5)
                changed |= np.abs(p - c) > 0.1 * np.maximum(np.abs(c), 1e-9)
            else:
                changed = np.abs(p - c) > 0.1 * np.maximum(np.abs(c), 1e-9)
            shares.append(float(changed.mean()))
        report["feature_shift"][name] = {"share_changed_gt10pct_mean": float(np.mean(shares)),
                                         "min": float(min(shares)), "max": float(max(shares))}

    for name, (fname, thr) in EVAL_MODELS.items():
        d = pickle.loads((MODELS / fname).read_bytes())
        thr = thr if thr is not None else d["threshold"]
        cols = [FEATURES.index(c) for c in d["features"]]

        def run(rows, mask):
            X = np.array([[r[c] for c in cols] for r, ok in zip(rows, mask) if ok], dtype=float)
            sub = test[mask]
            prob = d["model"].predict_proba(X)[:, 1]
            cl, _ = client_table(sub, prob)
            cm = confusion(cl["y"], cl["score"], thr)
            return {"clients": len(cl), "roc_auc": float(roc_auc_score(cl["y"], cl["score"])),
                    "recall": rates(cm)["recall"]["point"], "fpr": rates(cm)["fpr"]["point"], **cm}

        allm = np.ones(len(test), dtype=bool)
        control = run(variants[0], allm)
        draws = [run(variants[d + 1], keep[d]) for d in range(5)]
        summ = {m: {"control": control[m], "draw_mean": float(np.mean([x[m] for x in draws])),
                    "draw_min": float(min(x[m] for x in draws)), "draw_max": float(max(x[m] for x in draws)),
                    "max_abs_change": float(max(abs(x[m] - control[m]) for x in draws))}
                for m in ("roc_auc", "recall", "fpr")}
        verdict = (summ["roc_auc"]["max_abs_change"] > 0.01 or summ["recall"]["max_abs_change"] > 0.01
                   or summ["fpr"]["max_abs_change"] > 0.005)
        report["models"][name] = {"threshold": thr, "control": control, "draws": draws, "summary": summ,
                                  "resolution_sensitive_per_declared_rule": bool(verdict)}
        print(f"{name:32s} AUC {control['roc_auc']:.4f} -> {summ['roc_auc']['draw_mean']:.4f} "
              f"[{summ['roc_auc']['draw_min']:.4f},{summ['roc_auc']['draw_max']:.4f}]  "
              f"recall {control['recall']:.3f} -> {summ['recall']['draw_mean']:.3f} "
              f"[{summ['recall']['draw_min']:.3f},{summ['recall']['draw_max']:.3f}]  "
              f"FPR {control['fpr']:.4f} -> {summ['fpr']['draw_mean']:.4f} "
              f"[{summ['fpr']['draw_min']:.4f},{summ['fpr']['draw_max']:.4f}]  sensitive={verdict}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print("dropped sessions per draw:", report["dropped_sessions_per_draw"])
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

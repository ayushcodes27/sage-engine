#!/usr/bin/env python3
"""
Markov-chain baseline (B3), exactly as declared in configs/offline_protocol_v1.json -> models.baseline_markov.

  python evaluate_markov.py [--out results/offline/eclog6m_markov_baseline.json] [--bootstrap 2000]

1. extract (cached in ml_pipeline/data/eclog6m_prefix_paths.jsonl.gz, ~4 min): stream eclog.zip with the session
   builder's partition/sort/sessionise logic and keep, for every scored known-label session, the canonical
   non-static paths up to and including the first scoring request. Each sequence is checked against the session
   table (length == score_non_static_count), so any divergence from the builder aborts.
2. fit: first-order chain per class on train-split sequences; paths in < 5 train sessions -> <UNK>; add-one
   smoothing; score = (log P(seq|bot) - log P(seq|human)) / #transitions.
3. threshold = smallest with VALIDATION client FPR <= 1 % (also 5 %), applied to test; client score = max over
   its scored sessions; same metrics/CIs as evaluate_eclog6m.py (reused).
"""

import argparse
import csv
import gzip
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "evaluate"))
import build_eclog_sessions as B  # noqa: E402
from evaluate_eclog6m import FAMILY_CSV, P1, P11, SEED, auc_block, fold_of, rates, sha256  # noqa: E402
from gateway_emulator import SESSION_GAP_S  # noqa: E402
from label_eclog import extract_path, is_static_asset  # noqa: E402
from make_eclog6m_split import SESSIONS_6M, split_of  # noqa: E402
from offline_metrics import client_table, confusion, threshold_at_fpr  # noqa: E402
from campaign_metrics import clopper_pearson  # noqa: E402

DATA = REPO / "ml_pipeline" / "data"
CACHE = DATA / "eclog6m_prefix_paths.jsonl.gz"
MIN_COUNT = 5
UNK, START = "<UNK>", "<START>"
WANTED = {}  # (IpId, session_idx) -> score_non_static_count, set before fork


def bucket_sequences(args):
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
                    want = WANTED.get((client[0][0], s_idx))
                    if want is not None:
                        sess = client[start:k]
                        times = [r[1] / B.TICKS_PER_S for r in sess]
                        paths, ns = [], 0
                        for t, r in zip(times, sess):
                            p = extract_path(r[3])
                            if not is_static_asset(p):
                                paths.append(p)
                                ns += 1
                            if ns > 20 and t - times[0] >= 3:  # checked after every request, as first_score
                                break
                        if len(paths) != want:
                            raise RuntimeError(f"prefix length {len(paths)} != table {want} for {client[0][0]}/{s_idx}")
                        out.write(json.dumps([client[0][0], s_idx, paths]) + "\n")
                        n += 1
                    s_idx += 1
                    start = k
            i = j
    return n


def extract(sessions):
    scored = sessions[(sessions["scored"] == 1) & (sessions["label"] != "unknown")]
    WANTED.update(zip(zip(scored["IpId"], scored["session_idx"]), scored["score_non_static_count"].astype(int)))
    tmp = DATA / "eclog6m_markov.buckets"
    t0 = time.time()
    B.partition(DATA / "eclog.zip", tmp, 64)
    parts = [(tmp / f"b{i:03d}.tsv", tmp / f"q{i:03d}.jsonl.gz") for i in range(64)]
    with mp.Pool(max(1, (mp.cpu_count() or 2) - 2)) as pool:
        total = sum(pool.imap_unordered(bucket_sequences, parts))
    if total != len(WANTED):
        raise RuntimeError(f"extracted {total} sequences, expected {len(WANTED)}")
    with open(CACHE, "wb") as f:
        for _, q in sorted(parts):
            f.write(q.read_bytes())
    for b, q in parts:
        b.unlink()
        q.unlink()
    tmp.rmdir()
    print(f"extracted {total:,} prefix sequences in {time.time() - t0:.0f} s", flush=True)


def load_sequences():
    with gzip.open(CACHE, "rt") as f:
        return {(ip, s): paths for ip, s, paths in map(json.loads, f)}


class Markov:
    def __init__(self, seqs_by_class):
        sess_count = Counter()
        for seqs in seqs_by_class.values():
            for s in seqs:
                sess_count.update(set(s))
        self.vocab = {p for p, c in sess_count.items() if c >= MIN_COUNT} | {UNK, START}
        self.logp = {}
        v = len(self.vocab)
        for cls, seqs in seqs_by_class.items():
            trans, out = Counter(), Counter()
            for s in seqs:
                s = [START] + self.map(s)
                for a, b in zip(s, s[1:]):
                    trans[(a, b)] += 1
                    out[a] += 1
            self.logp[cls] = (trans, out, v)

    def map(self, s):
        return [p if p in self.vocab else UNK for p in s]

    def loglik(self, cls, s):
        trans, out, v = self.logp[cls]
        s = [START] + self.map(s)
        return sum(np.log((trans.get((a, b), 0) + 1) / (out.get(a, 0) + v)) for a, b in zip(s, s[1:]))

    def score(self, s):
        return (self.loglik("bot", s) - self.loglik("human", s)) / max(1, len(s))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "results" / "offline" / "eclog6m_markov_baseline.json"))
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    sessions = pd.read_csv(SESSIONS_6M)
    sessions["split"] = sessions["IpId"].map(split_of(sessions["IpId"]))
    if not CACHE.exists():
        extract(sessions)
    seqs = load_sequences()
    scored = sessions[(sessions["scored"] == 1) & (sessions["label"] != "unknown")].copy()
    scored["seq"] = [seqs[(ip, s)] for ip, s in zip(scored["IpId"], scored["session_idx"])]
    train, val, test = (scored[scored["split"] == s] for s in ("train", "validation", "test"))

    model = Markov({c: train.loc[train["label"] == c, "seq"].tolist() for c in ("bot", "human")})
    vscore = np.array([model.score(s) for s in val["seq"]])
    tscore = np.array([model.score(s) for s in test["seq"]])
    vc, _ = client_table(val, vscore)
    tc, tmixed = client_table(test, tscore)
    vh = vc.loc[vc["y"] == 0, "score"]
    fam = pd.read_csv(FAMILY_CSV)
    folds = json.loads(P11.read_text())["folds"]
    client_fold = {ip: fold_of(f, folds) for ip, f in zip(fam["IpId"], fam["family"])}

    ops = {}
    for name, fpr in (("validation_fpr_le_1pct", 0.01), ("validation_fpr_le_5pct", 0.05)):
        t = threshold_at_fpr(vh, fpr)
        ops[name] = rates(confusion(tc["y"], tc["score"], t)) | {"threshold": t}
        bots = tc[tc["y"] == 1].assign(fold=lambda x: x["IpId"].map(client_fold).fillna("untagged"))
        ops[name]["test_recall_by_crawler_fold"] = {
            f: clopper_pearson(int((g["score"] >= t).sum()), len(g)) for f, g in bots.groupby("fold")}
    report = {
        "protocol": {"path": str(P1.relative_to(REPO)), "sha256": sha256(P1)},
        "inputs": {"session_table_sha256": sha256(SESSIONS_6M), "prefix_paths_sha256": sha256(CACHE),
                   "script_sha256": sha256(__file__), "seed": SEED, "bootstrap_resamples": args.bootstrap},
        "model": {"order": 1, "min_train_sessions_per_path": MIN_COUNT, "vocab_size": len(model.vocab),
                  "train_sequences": {c: int((train["label"] == c).sum()) for c in ("bot", "human")}},
        "client_level": {"n_bot": int(tc["y"].sum()), "n_human": int((tc["y"] == 0).sum()),
                         "mixed_label_clients_excluded": tmixed,
                         **auc_block(tc["y"], tc["score"], args.bootstrap, rng), "operating_points": ops},
        "session_level": {"n": len(test), "roc_auc": None},
    }
    from sklearn.metrics import roc_auc_score
    report["session_level"]["roc_auc"] = float(roc_auc_score((test["label"] == "bot").astype(int), tscore))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    cl = report["client_level"]
    print(f"Markov client AUC {cl['roc_auc']:.4f} PR-AUC {cl['pr_auc']:.4f}")
    for k, o in ops.items():
        print(f"  {k}: recall {o['recall']['point']:.3f} ({o['tp']}/{o['tp'] + o['fn']}), FPR {o['fpr']['point']:.4f}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

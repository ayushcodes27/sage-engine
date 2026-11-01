#!/usr/bin/env python3
"""
Client-grouped train / validation / test split of the six-month EClog sessions (B3), declared before any
model is trained on them.

  python make_eclog6m_split.py            # writes configs/split_eclog6m_v1.json

1. The one-day sample (training data of the frozen models) was anonymised separately: its IpIds differ
   from the six-month file's. Its sessions are found in the six-month table by (start, end, request
   count); a six-month client is a *candidate* for a one-day client if they share any such session.
2. Every six-month client that is a candidate for a frozen-model TRAINING client
   (ml_pipeline/models/eclog_weak_split_manifest.json) is forced into train, so no client the frozen
   models were fitted on can reach validation or test (conservative: ambiguous candidates included).
3. All other clients: bucket = sha256(SALT + IpId) mod 100; < 60 train, < 80 validation, else test.

The assignment is deterministic; the config stores the rule, the forced-train list and a SHA-256 of the
full sorted assignment, which split_of() recomputes and checks.
"""

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
SESSIONS_6M = REPO / "ml_pipeline" / "data" / "eclog6m_sessions.csv.gz"
SESSIONS_1D = REPO / "ml_pipeline" / "data" / "eclog1d_sessions.csv.gz"
FROZEN_SPLIT = REPO / "ml_pipeline" / "models" / "eclog_weak_split_manifest.json"
OUT = REPO / "configs" / "split_eclog6m_v1.json"
SALT = "sage-jnsm-eclog6m-split-v1"
KEY = ["start_ticks", "end_ticks", "n_requests"]


def bucket(ip):
    return int(hashlib.sha256((SALT + ip).encode()).hexdigest(), 16) % 100


def assign(ips, forced_train):
    out = {}
    for ip in ips:
        if ip in forced_train:
            out[ip] = "train"
        else:
            b = bucket(ip)
            out[ip] = "train" if b < 60 else ("validation" if b < 80 else "test")
    return out


def assignment_sha256(assignment):
    blob = "\n".join(f"{ip}\t{s}" for ip, s in sorted(assignment.items()))
    return hashlib.sha256(blob.encode()).hexdigest()


def split_of(sessions_ips, config_path=OUT):
    """Recompute the assignment for the given IpIds from a committed config and verify its hash."""
    cfg = json.loads(Path(config_path).read_text())
    a = assign(sorted(set(sessions_ips)), set(cfg["forced_train_clients"]))
    if assignment_sha256(a) != cfg["assignment_sha256"]:
        raise SystemExit("split assignment does not reproduce the committed hash (different session table?)")
    return a


def main():
    six = pd.read_csv(SESSIONS_6M, usecols=["IpId", "label", "scored"] + KEY)
    one = pd.read_csv(SESSIONS_1D, usecols=["IpId"] + KEY)
    frozen = json.loads(FROZEN_SPLIT.read_text())
    frozen_train = set(frozen["train_clients"])

    joined = one.merge(six[["IpId"] + KEY], on=KEY, suffixes=("_1d", "_6m"))
    candidates = defaultdict(set)
    for a, b in zip(joined["IpId_1d"], joined["IpId_6m"]):
        candidates[a].add(b)
    unmatched_1d_sessions = int(len(one.merge(six[KEY].drop_duplicates(), on=KEY, how="left", indicator=True)
                                    .query("_merge == 'left_only'")))
    forced = sorted({b for a in frozen_train for b in candidates.get(a, ())})

    ips = sorted(six["IpId"].unique())
    assignment = assign(ips, set(forced))
    six["split"] = six["IpId"].map(assignment)

    def counts(df):
        return {s: {"clients": int(g["IpId"].nunique()), "sessions": int(len(g)),
                    "scored_sessions": int(g["scored"].sum()),
                    "scored_clients": int(g.loc[g["scored"] == 1, "IpId"].nunique())}
                for s, g in df.groupby("split")}

    cfg = {
        "name": "split_eclog6m_v1",
        "rule": "forced_train if candidate of a frozen-model training client, else sha256(salt+IpId) % 100: "
                "<60 train, <80 validation, else test",
        "salt": SALT,
        "session_table": {"path": str(SESSIONS_6M.relative_to(REPO)),
                          "sha256": hashlib.sha256(SESSIONS_6M.read_bytes()).hexdigest(),
                          "builder": "ml_pipeline/scripts/train/build_eclog_sessions.py"},
        "one_day_matching": {
            "one_day_clients": int(one["IpId"].nunique()), "one_day_clients_matched": len(candidates),
            "one_day_clients_with_several_candidates": sum(len(v) > 1 for v in candidates.values()),
            "one_day_sessions_unmatched": unmatched_1d_sessions,
            "frozen_train_clients": len(frozen_train),
            "frozen_train_clients_matched": sum(1 for a in frozen_train if a in candidates),
            "note": "one-day and six-month IpIds are anonymised independently; matching is by session "
                    "(start, end, request count); unmatched one-day sessions lie at the window edges where "
                    "the six-month log continues the session",
        },
        "forced_train_clients": forced,
        "assignment_sha256": assignment_sha256(assignment),
        "counts_by_split": counts(six),
        "counts_by_split_and_label": {lab: counts(g) for lab, g in six.groupby("label")},
    }
    OUT.write_text(json.dumps(cfg, indent=2) + "\n")
    print(json.dumps({k: v for k, v in cfg.items() if k != "forced_train_clients"}, indent=2))


if __name__ == "__main__":
    sys.exit(main())

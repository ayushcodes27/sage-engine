#!/usr/bin/env python3
"""
Parity check: build_eclog_sessions.py run on eclog_1day.csv must reproduce the committed training table
ml_pipeline/data/eclog_weak_labeled.csv (label_eclog.py output, the frozen models' training data).

  python check_session_builder_parity.py ml_pipeline/data/eclog1d_sessions.csv.gz [--report results/...json]

Sessions are matched on session_id = <IpId>_sess<index>. Reports, per column, how many sessions agree
(features within 1e-6 relative). label_eclog.py sorts with an unstable sort, so requests sharing a
timestamp at the 50-request window boundary may legitimately differ; those cases are listed, not hidden.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ml_pipeline" / "scripts" / "train"))
from gateway_emulator import FEATURES  # noqa: E402

COMMITTED = REPO / "ml_pipeline" / "data" / "eclog_weak_labeled.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("built")
    ap.add_argument("--report")
    args = ap.parse_args()

    ref = pd.read_csv(COMMITTED)
    new = pd.read_csv(args.built)
    new["session_id"] = new["IpId"].astype(str) + "_sess" + new["session_idx"].astype(str)
    m = ref.merge(new, on="session_id", how="outer", indicator=True, suffixes=("_ref", ""))
    both = m[m["_merge"] == "both"]
    report = {
        "committed_sessions": int(len(ref)), "built_sessions": int(len(new)),
        "matched_sessions": int(len(both)),
        "only_committed": int((m["_merge"] == "left_only").sum()), "only_built": int((m["_merge"] == "right_only").sum()),
        "label_agree": int((both["label_ref"] == both["label"]).sum()),
        "label_confidence_agree": int((both["label_confidence_ref"] == both["label_confidence"]).sum()),
        "features": {},
    }
    for c in FEATURES:
        a, b = both[c].astype(float), both[f"done_{c}"].astype(float)
        ok = [math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-9) for x, y in zip(a, b)]
        bad = both.loc[[not o for o in ok], "session_id"].tolist()
        report["features"][c] = {"agree": int(sum(ok)), "disagree": len(bad), "disagree_sessions": bad[:50]}
    all_ok = (report["only_committed"] == 0 and report["only_built"] == 0
              and report["label_agree"] == len(both) and report["label_confidence_agree"] == len(both)
              and all(v["disagree"] == 0 for v in report["features"].values()))
    report["exact_parity"] = all_ok
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text + "\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

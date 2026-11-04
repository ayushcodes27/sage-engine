#!/usr/bin/env python3
"""
Reconstructs a client manifest for a campaign run whose original manifest was not archived
(run A, diverse-8881bc1c). Nothing is inferred from model output:

- client set      = distinct userId values in the run's telemetry (filtered by runId)
- profile         = client_id with the trailing "-NN" index removed (the generator's naming rule,
                    load-tests/diverse-shadow-traffic.py: client_id = f"{profile_name}-{i:02d}")
- true_class      = fixed per profile (generator BASE_PROFILE_MATRIX expected_class)
- campaign_config = final_campaign_config.json read from the given git revision

request_count is left null (it was never recorded); observed telemetry event counts are stored
separately as observed_event_count. The output is marked "reconstructed": true.
"""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

PROFILE_CLASS = {
    "normal_browser": "human",
    "spa_client": "human",
    "mobile_browser": "human",
    "privacy_browser": "human",
    "slow_scraper": "bot",
    "asset_fetching_bot": "bot",
    "fast_scraper": "bot",
}


def open_text(path):
    return gzip.open(path, "rt", encoding="utf-8-sig") if str(path).endswith(".gz") else open(path, encoding="utf-8-sig")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telemetry", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config-rev", required=True, help="git revision holding final_campaign_config.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg_bytes = subprocess.run(
        ["git", "show", f"{args.config_rev}:final_campaign_config.json"], capture_output=True, check=True
    ).stdout
    cfg = json.loads(cfg_bytes.decode("utf-8"))

    counts = Counter()
    with open_text(args.telemetry) as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("runId") == args.run_id:
                counts[e.get("userId")] += 1

    clients = {}
    for cid in sorted(counts):
        profile = re.sub(r"-\d+$", "", cid)
        if profile not in PROFILE_CLASS:
            raise SystemExit(f"Unexpected client id {cid!r}: profile {profile!r} not in generator profile list")
        clients[cid] = {
            "client_id": cid,
            "profile": profile,
            "expected_label": PROFILE_CLASS[profile],
            "true_class": PROFILE_CLASS[profile],
            "run_id": args.run_id,
            "request_count": None,
            "observed_event_count": counts[cid],
        }

    manifest = {
        "run_id": args.run_id,
        "reconstructed": True,
        "reconstruction_method": __doc__.strip(),
        "telemetry_sha256": hashlib.sha256(Path(args.telemetry).read_bytes()).hexdigest(),
        "run_mode": cfg.get("run_mode", "final"),
        "campaign_config_rev": args.config_rev,
        "campaign_config_hash": hashlib.sha256(cfg_bytes).hexdigest(),
        "campaign_config": cfg,
        "seeds": cfg.get("profile_seeds"),
        "profile_matrix": {p: {"expected_class": c} for p, c in PROFILE_CLASS.items()},
        "clients": clients,
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(clients)} clients, profiles {dict(Counter(v['profile'] for v in clients.values()))} -> {args.out}")


if __name__ == "__main__":
    main()

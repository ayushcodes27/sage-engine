#!/usr/bin/env python3
"""
Exports one campaign run's telemetry from Kafka (via the broker container's console consumer, no extra
dependencies), compresses it deterministically and records SHA-256 digests next to the manifest.

  python archive_campaign_run.py --run-id diverse-xxxxxxxx --manifest <manifest.json> --out telemetry/campaign_c

Writes <out>/<run_id>/{telemetry_<run_id>.jsonl.gz, manifest_<run_id>.json, SHA256SUMS}. The raw uncompressed
digest and the event counts are printed; every event of the topic is kept only if it carries this runId.
"""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default="telemetry/campaign_c")
    ap.add_argument("--container", default="sage-kafka")
    ap.add_argument("--timeout-ms", type=int, default=30000)
    args = ap.parse_args()

    out = Path(args.out) / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    raw = out / f"telemetry_{args.run_id}.jsonl"
    proc = subprocess.run(
        ["docker", "exec", args.container, "kafka-console-consumer", "--bootstrap-server", "kafka:29092",
         "--topic", "gateway-telemetry", "--from-beginning", "--timeout-ms", str(args.timeout_ms)],
        capture_output=True, text=True, check=False)
    kept = total = 0
    needle = f'"{args.run_id}"'
    with open(raw, "w", encoding="utf-8") as f:
        for line in proc.stdout.splitlines():
            total += 1
            if needle in line:
                try:
                    if json.loads(line).get("runId") == args.run_id:
                        f.write(line + "\n")
                        kept += 1
                except json.JSONDecodeError:
                    pass
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    gz = out / f"{raw.name}.gz"
    with open(raw, "rb") as fin, open(gz, "wb") as fout:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fout, compresslevel=9, mtime=0) as z:
            shutil.copyfileobj(fin, z)
    raw.unlink()
    man = out / f"manifest_{args.run_id}.json"
    shutil.copyfile(args.manifest, man)
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in (gz, man)]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print(f"topic events {total}, kept {kept} for {args.run_id}; uncompressed sha256 {raw_sha}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

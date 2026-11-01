#!/usr/bin/env python3
"""
Download the public B3 datasets pinned in configs/datasets.json and verify them.

  python ml_pipeline/scripts/data/fetch_datasets.py [--dest ml_pipeline/data] [--only eclog.zip ...]

Every file is verified against its Dataverse-published MD5 (for ingested tabular files that is the MD5
of the original upload, which is why eclog_1day.csv is fetched in original format). A mismatch exits 1
and leaves the file in place for inspection; nothing is ever deleted. SHA-256 of every file is written to <dest>/fetch_manifest.json (gitignored with
the data) and printed, so it can be copied into a committed report.

EClog downloads are gated by a Dataverse guestbook (name, email, institution, position). If the API
refuses, the script prints where to put a browser-downloaded copy; files already present in --dest are
verified, not re-downloaded. This script never submits guestbook data.

Zanbil.ir (doi:10.7910/DVN/3QBYB5) is restricted on Dataverse and is not fetched by this script.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "configs" / "datasets.json"
API = "https://dataverse.harvard.edu/api/access/datafile/{id}"


def digests(path):
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def download(file_id, fmt, out):
    url = API.format(id=file_id) + (f"?format={fmt}" if fmt else "")
    tmp = out.with_suffix(out.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)
    tmp.rename(out)
    return url


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=str(REPO / "ml_pipeline" / "data"))  # label_eclog.py input dir
    ap.add_argument("--only", nargs="*", help="file names to fetch (default: all EClog files)")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())["eclog"]
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / "fetch_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    for name, spec in cfg["files"].items():
        if args.only and name not in args.only:
            continue
        out = dest / name
        url = API.format(id=spec["file_id"]) + (f"?format={spec['download_format']}" if spec["download_format"] else "")
        if not out.exists():
            print(f"downloading {name} from {url}")
            try:
                download(spec["file_id"], spec["download_format"], out)
            except urllib.error.HTTPError as e:
                sys.exit(f"{name}: HTTP {e.code} from Dataverse ({e.read()[:200].decode(errors='replace')}).\n"
                         f"{cfg['access']}\nExpected path: {out}")
        md5, sha = digests(out)
        entry = {"doi": cfg["doi"], "url": url, "size": out.stat().st_size, "md5": md5, "sha256": sha,
                 "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        if md5 != spec["md5"] or (spec["size"] and out.stat().st_size != spec["size"]):
            sys.exit(f"{name}: checksum mismatch (got md5 {md5}, expected {spec['md5']}); file left in place at {out}")
        entry["verification"] = "dataverse_md5"
        manifest[name] = entry
        print(f"{name}: {entry['verification']} sha256={sha}")

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()

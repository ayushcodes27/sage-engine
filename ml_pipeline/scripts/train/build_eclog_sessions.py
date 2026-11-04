#!/usr/bin/env python3
"""
Build per-session rows from EClog (one-day CSV or the six-month zip) for B3.

  python build_eclog_sessions.py --input ml_pipeline/data/eclog.zip --out ml_pipeline/data/eclog6m_sessions.csv.gz
  python build_eclog_sessions.py --input ml_pipeline/data/eclog_1day.csv --out ml_pipeline/data/eclog1d_sessions.csv.gz

Pipeline (streams; never holds the whole log in memory):
  1. partition: rows -> N bucket files by hash(IpId); each row keeps IpId, ticks, its input row number,
     the URI and a weak label code from the user agent (label_eclog.get_label_and_confidence, cached per UA).
  2. per bucket: sort each client's rows stably by (ticks, input row), sessionise (gap > 300 s), label the
     session as label_eclog.py does (>= 80 % bot / human rows, else unknown), and emit
       - completed-session features (label_eclog.py definitions: last 50 non-static requests, session counters),
       - the gateway's first-score prefix row (gateway_emulator.first_score: f0 > 20 and duration >= 3 s),
       - session totals used for coverage at any k (non-static count, duration).

Timestamps are .NET ticks (100 ns); EClog stores them at 1 s resolution (see audit N1).
"""

import argparse
import csv
import gzip
import hashlib
import io
import multiprocessing as mp
import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway_emulator import FEATURES, SESSION_GAP_S, first_score, window_features  # noqa: E402
from label_eclog import extract_path, get_label_and_confidence, is_cart_uri, is_static_asset  # noqa: E402

csv.field_size_limit(1 << 24)
LABEL_CODE = {("bot", "high"): "BH", ("bot", "medium"): "BM", ("human", "high"): "H", ("unknown", "none"): "U"}
TICKS_PER_S = 10_000_000


def bucket_of(ip, n):
    return int.from_bytes(hashlib.blake2b(ip.encode(), digest_size=4).digest(), "big") % n


def open_rows(path):
    path = Path(path)
    if path.suffix == ".zip":
        z = zipfile.ZipFile(path)
        (member,) = [m for m in z.namelist() if m.endswith(".csv")]
        return csv.DictReader(io.TextIOWrapper(z.open(member), encoding="utf-8", errors="replace", newline=""))
    return csv.DictReader(open(path, encoding="utf-8", errors="replace", newline=""))


def partition(inp, tmp, n_buckets):
    tmp.mkdir(parents=True, exist_ok=True)
    files = [open(tmp / f"b{i:03d}.tsv", "w", newline="") for i in range(n_buckets)]
    writers = [csv.writer(f, delimiter="\t") for f in files]
    ua_cache, t0, n = {}, time.time(), 0
    for n, row in enumerate(open_rows(inp)):
        ua = row["UserAgent"]
        code = ua_cache.get(ua)
        if code is None:
            code = ua_cache[ua] = LABEL_CODE[get_label_and_confidence(ua)]
        ip = row["IpId"]
        writers[bucket_of(ip, n_buckets)].writerow((ip, row["TimeStamp"], n, row["Uri"], code))
        if n % 5_000_000 == 0 and n:
            print(f"  partitioned {n:,} rows ({time.time() - t0:.0f} s, {len(ua_cache):,} distinct UAs)", flush=True)
    for f in files:
        f.close()
    return n + 1, len(ua_cache)


def session_label(codes):
    total = len(codes)
    bots = sum(1 for c in codes if c in ("BH", "BM"))
    humans = sum(1 for c in codes if c == "H")
    if bots / total >= 0.80:
        return "bot", ("medium" if "BM" in codes else "high")
    if humans / total >= 0.80:
        return "human", "high"
    return "unknown", "none"


def completed_features(times_s, uris):
    """label_eclog.py session features: counters over all hits, window = last 50 non-static requests."""
    paths = [extract_path(u) for u in uris]
    static = [is_static_asset(p) for p in paths]
    cart = sum(1 for p in paths if is_cart_uri(p))
    ns = [(t, p) for t, p, s in zip(times_s, paths, static) if not s][-50:]
    return window_features([t for t, _ in ns], [p for _, p in ns], len(paths), cart, sum(static))


def process_bucket(args):
    path, out_path = args
    rows = []
    with open(path, newline="") as f:
        for ip, ticks, rowno, uri, code in csv.reader(f, delimiter="\t"):
            rows.append((ip, int(ticks), int(rowno), uri, code))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))  # client, time, input order (stable tie-break)
    out = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j][0] == rows[i][0]:
            j += 1
        client = rows[i:j]
        s_idx, start = 0, 0
        for k in range(1, len(client) + 1):
            if k == len(client) or (client[k][1] - client[k - 1][1]) / TICKS_PER_S > SESSION_GAP_S:
                out.append(session_row(client[start:k], s_idx))
                s_idx += 1
                start = k
        i = j
    with gzip.open(out_path, "wt", newline="") as f:
        w = csv.writer(f)
        for r in out:
            w.writerow(r)
    return len(out)


HEADER = (["IpId", "session_idx", "start_ticks", "end_ticks", "label", "label_confidence", "n_requests",
           "n_non_static", "duration_s"]
          + [f"done_{c}" for c in FEATURES]
          + ["scored", "score_request_idx", "score_non_static_count", "score_duration_s"]
          + [f"pre_{c}" for c in FEATURES])


def session_row(sess, s_idx):
    times = [r[1] / TICKS_PER_S for r in sess]
    uris = [r[3] for r in sess]
    label, conf = session_label([r[4] for r in sess])
    done = completed_features(times, uris)
    n_ns = sum(1 for u in uris if not is_static_asset(extract_path(u)))
    fs = first_score(times, uris)
    if fs:
        idx, ns, dur, pre = fs
        score = [1, idx, ns, round(dur, 6)] + [pre[c] for c in FEATURES]
    else:
        score = [0, "", "", ""] + [""] * len(FEATURES)
    return ([sess[0][0], s_idx, sess[0][1], sess[-1][1], label, conf, len(sess), n_ns, round(times[-1] - times[0], 6)]
            + [done[c] for c in FEATURES] + score)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmp", default=None, help="bucket directory (default: <out>.buckets)")
    ap.add_argument("--buckets", type=int, default=64)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()

    out = Path(args.out)
    tmp = Path(args.tmp) if args.tmp else out.with_suffix(".buckets")
    t0 = time.time()
    n_rows, n_ua = partition(args.input, tmp, args.buckets)
    print(f"partitioned {n_rows:,} rows, {n_ua:,} distinct user agents in {time.time() - t0:.0f} s", flush=True)

    parts = [(tmp / f"b{i:03d}.tsv", tmp / f"s{i:03d}.csv.gz") for i in range(args.buckets)]
    with mp.Pool(args.workers) as pool:
        n_sessions = sum(pool.imap_unordered(process_bucket, parts))
    with gzip.open(out, "wt", newline="") as f:
        csv.writer(f).writerow(HEADER)
    with open(out, "ab") as f:  # concatenated gzip members are one valid gzip stream
        for _, part in sorted(parts):
            f.write(part.read_bytes())
    for b, s in parts:
        b.unlink()
        s.unlink()
    tmp.rmdir()
    print(f"wrote {n_sessions:,} sessions to {out} in {time.time() - t0:.0f} s "
          f"(input rows {n_rows:,}, sha256 {hashlib.sha256(out.read_bytes()).hexdigest()})")


if __name__ == "__main__":
    main()

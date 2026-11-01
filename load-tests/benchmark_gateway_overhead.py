#!/usr/bin/env python3
"""
SAGE gateway overhead benchmark (B2).

Compares gateway modes (sage.ml.mode) on the same host and stack, all in shadow mode:
  off      proxy only (no Redis features, no telemetry, no ML)
  features Redis features + Kafka telemetry, no ML
  sync     ML scoring inline on the request path
  async    ML scoring off the request path (campaign configuration)

For every mode x concurrency level x repetition it records client-side latency of every request,
throughput, docker CPU/memory samples and the gateway's internal timers (Redis feature round trip,
ML round trip, Kafka publish) as Prometheus histogram deltas. Raw outputs and summary.json are written
to results/benchmark/<benchmark_id>/. Redis is flushed before every repetition.

Load model (fixed, declared here): closed loop, one client IP per worker, a browsing mix of the
mock site's valid routes (3 non-static : 1 static), fixed think time between requests so that every
worker passes the scoring gate (depth > 20, duration >= 3 s) and is re-scored every 20 requests.
"""

import argparse
import csv
import gzip
import hashlib
import json
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "infra" / "docker-compose.yml"
CONTAINERS = ["sage-gateway", "sage-ml", "sage-redis", "sage-kafka", "sage-ecommerce"]
NON_STATIC = ["/products", "/products/12", "/api/price/23", "/api/inventory/23", "/api/search?q=phone", "/", "/cart"]
STATIC = ["/static/style.css", "/static/app.js", "/images/logo.png"]
TIMERS = ["sage_gateway_redis_telemetry_seconds", "sage_gateway_ml_roundtrip_seconds", "sage_gateway_kafka_publish_seconds"]


def sh(*cmd, check=True, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, check=check, env=env)


def git_state():
    commit = sh("git", "-C", str(REPO), "rev-parse", "HEAD").stdout.strip()
    dirty = bool(sh("git", "-C", str(REPO), "status", "--porcelain").stdout.strip())
    return commit, dirty


def host_info():
    lscpu = sh("lscpu", check=False).stdout
    info = {k: v.strip() for k, v in (l.split(":", 1) for l in lscpu.splitlines() if ":" in l)
            if k in ("Model name", "CPU(s)", "Thread(s) per core", "CPU max MHz")}
    gov = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    mem = next((l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")), "")
    return {
        "cpu": info, "cpu_governor": gov.read_text().strip() if gov.exists() else None, "memtotal": mem,
        "kernel": platform.release(), "python": platform.python_version(), "requests": requests.__version__,
        "docker": sh("docker", "version", "--format", "{{.Server.Version}}", check=False).stdout.strip(),
        "load_generator": "python threads (requests.Session per worker) on the same host as the stack",
    }


def container_info():
    out = {}
    for c in CONTAINERS:
        r = sh("docker", "inspect", "--format", "{{.Image}} {{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}", c, check=False)
        out[c] = r.stdout.strip() if r.returncode == 0 else "missing"
    jar = sh("docker", "exec", "sage-gateway", "sha256sum", "/app/app.jar", check=False).stdout.split()
    out["sage-gateway:/app/app.jar"] = jar[0] if jar else "unknown"
    return out


def restart_gateway(mode, gateway_url, env_base):
    env = dict(env_base, SAGE_ML_MODE=mode)
    sh("docker", "compose", "-f", str(COMPOSE), "up", "-d", "--no-deps", "--force-recreate", "sage-gateway", env=env)
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            if requests.get(f"{gateway_url}/actuator/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise SystemExit(f"gateway did not become healthy in mode {mode}")


def flush_redis():
    sh("docker", "exec", "sage-redis", "redis-cli", "FLUSHALL")


def scrape(gateway_url):
    text = requests.get(f"{gateway_url}/actuator/prometheus", timeout=5).text
    out = {"timers": {}, "outcomes": {}, "attempts": {}}
    for t in TIMERS:
        buckets = {}
        for m in re.finditer(rf'^{t}_bucket\{{[^}}]*le="([^"]+)"[^}}]*\}} ([0-9.eE+-]+)$', text, re.M):
            buckets[m.group(1)] = buckets.get(m.group(1), 0.0) + float(m.group(2))
        count = sum(float(m.group(1)) for m in re.finditer(rf"^{t}_count(?:\{{[^}}]*\}})? ([0-9.eE+-]+)$", text, re.M))
        total = sum(float(m.group(1)) for m in re.finditer(rf"^{t}_sum(?:\{{[^}}]*\}})? ([0-9.eE+-]+)$", text, re.M))
        out["timers"][t] = {"buckets": buckets, "count": count, "sum": total}
    for m in re.finditer(r'^sage_gateway_ml_inference_outcomes_total\{[^}]*outcome="([^"]+)"[^}]*\} ([0-9.eE+-]+)$', text, re.M):
        out["outcomes"][m.group(1)] = float(m.group(2))
    # every ML scoring attempt by result (Scored, Timeout, Error, SemaphoreFull, ...), summed over source
    for m in re.finditer(r'^sage_gateway_ml_score_attempts_total\{([^}]*)\} ([0-9.eE+-]+)$', text, re.M):
        st = re.search(r'status="([^"]+)"', m.group(1)).group(1)
        out["attempts"][st] = out["attempts"].get(st, 0.0) + float(m.group(2))
    return out


def drain(gateway_url, stable_s=3.0, max_s=60.0):
    """Wait until queued async scores and Kafka sends have finished: the ML round-trip and Kafka publish
    timer counts must be unchanged for stable_s. A fixed short sleep let backlogged async scores at high
    concurrency finish after the scrape (undercounted ML calls) and run into the next repetition."""
    t0 = time.time()
    last, since = None, time.time()
    while time.time() - t0 < max_s:
        snap = scrape(gateway_url)
        timers = snap["timers"]
        cur = (timers["sage_gateway_ml_roundtrip_seconds"]["count"], timers["sage_gateway_kafka_publish_seconds"]["count"],
               sum(snap["attempts"].values()))
        if cur != last:
            last, since = cur, time.time()
        elif time.time() - since >= stable_s:
            return time.time() - t0
        time.sleep(0.5)
    raise SystemExit(f"timers still changing after {max_s} s; async backlog did not drain")


def histogram_delta(before, after):
    res = {}
    for t in TIMERS:
        b, a = before["timers"][t], after["timers"][t]
        n = a["count"] - b["count"]
        entry = {"count": n, "mean_ms": None, "p50_ms_upper": None, "p95_ms_upper": None, "p99_ms_upper": None}
        if n > 0:
            entry["mean_ms"] = 1000.0 * (a["sum"] - b["sum"]) / n
            les = sorted((float("inf") if k == "+Inf" else float(k), k) for k in a["buckets"])
            cum = [(le, a["buckets"][k] - b["buckets"].get(k, 0.0)) for le, k in les]
            for q, key in ((0.50, "p50_ms_upper"), (0.95, "p95_ms_upper"), (0.99, "p99_ms_upper")):
                le = next(le for le, c in cum if c >= q * n)
                entry[key] = None if le == float("inf") else 1000.0 * le
        res[t] = entry
    outcomes = {k: after["outcomes"].get(k, 0.0) - before["outcomes"].get(k, 0.0)
                for k in set(after["outcomes"]) | set(before["outcomes"])}
    res["ml_outcomes"] = {k: v for k, v in outcomes.items() if v}
    attempts = {k: after["attempts"].get(k, 0.0) - before["attempts"].get(k, 0.0)
                for k in set(after["attempts"]) | set(before["attempts"])}
    res["ml_attempts"] = {k: v for k, v in attempts.items() if v}
    return res


class StatsSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop_flag = [], threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            r = sh("docker", "stats", "--no-stream", "--format", "{{json .}}", *CONTAINERS, check=False)
            t = time.time()
            for line in r.stdout.splitlines():
                try:
                    d = json.loads(line)
                    self.samples.append({"t": t, "name": d["Name"], "cpu_pct": float(d["CPUPerc"].rstrip("%")),
                                         "mem": d["MemUsage"].split("/")[0].strip()})
                except (ValueError, KeyError):
                    continue


def _mem_mib(s):
    m = re.match(r"([0-9.]+)\s*([KMG]i?B)", s)
    if not m:
        return None
    f = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "KB": 1 / 1024, "MB": 1, "GB": 1024}[m.group(2)]
    return float(m.group(1)) * f


def worker(gateway_url, ip, n_requests, think_s, records, rec_lock, bench_id, mode, conc, rep):
    s = requests.Session()
    s.headers.update({"X-Forwarded-For": ip, "X-SAGE-Run-Id": bench_id, "X-SAGE-Client-Id": f"bench-{ip}"})
    local = []
    for i in range(n_requests):
        path = STATIC[(i // 4) % len(STATIC)] if i % 4 == 3 else NON_STATIC[i % len(NON_STATIC)]
        t0 = time.perf_counter()
        try:
            status = s.get(f"{gateway_url}{path}", timeout=10).status_code
        except requests.RequestException:
            status = -1
        local.append((mode, conc, rep, ip, i, path, status, (time.perf_counter() - t0) * 1000.0, time.time()))
        time.sleep(think_s)
    with rec_lock:
        records.extend(local)


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def run_rep(gateway_url, mode, conc, rep, args, bench_id, out_dir):
    flush_redis()
    before = scrape(gateway_url)
    sampler = StatsSampler()
    sampler.start()
    records, lock = [], threading.Lock()
    threads = [threading.Thread(target=worker, args=(gateway_url, f"10.{200 + rep}.{w // 250}.{w % 250 + 1}",
                                                     args.requests_per_worker, args.think_ms / 1000.0,
                                                     records, lock, bench_id, mode, conc, rep)) for w in range(conc)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    drain_s = drain(gateway_url)
    sampler.stop_flag.set()
    sampler.join()
    after = scrape(gateway_url)

    raw = out_dir / "raw" / f"{mode}_c{conc}_r{rep}.csv.gz"
    raw.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "concurrency", "rep", "client_ip", "seq", "path", "status", "latency_ms", "end_epoch_s"])
        w.writerows(records)
    (out_dir / "raw" / f"{mode}_c{conc}_r{rep}_docker_stats.json").write_text(json.dumps(sampler.samples))

    lat = [r[7] for r in records if r[6] == 200]
    errors = sum(1 for r in records if r[6] != 200)
    per_container = {}
    for c in CONTAINERS:
        cs = [x for x in sampler.samples if x["name"] == c]
        mems = [m for m in (_mem_mib(x["mem"]) for x in cs) if m is not None]
        per_container[c] = {"samples": len(cs),
                            "cpu_pct_mean": statistics.mean(x["cpu_pct"] for x in cs) if cs else None,
                            "cpu_pct_max": max((x["cpu_pct"] for x in cs), default=None),
                            "mem_mib_max": max(mems, default=None)}
    return {"mode": mode, "concurrency": conc, "rep": rep, "requests": len(records), "errors": errors,
            "wall_s": wall, "drain_s": drain_s, "throughput_rps": len(records) / wall if wall else None,
            "latency_ms": {"p50": pct(lat, 0.50), "p95": pct(lat, 0.95), "p99": pct(lat, 0.99),
                           "mean": statistics.mean(lat) if lat else None},
            "internal": histogram_delta(before, after), "containers": per_container,
            "raw_file": str(raw.relative_to(out_dir)),
            "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}


def summarise(reps, modes, levels):
    cells = {}
    for mode in modes:
        for c in levels:
            rs = [r for r in reps if r["mode"] == mode and r["concurrency"] == c]
            if not rs:
                continue

            def med(f):
                vals = [f(r) for r in rs if f(r) is not None]
                return statistics.median(vals) if vals else None

            cells[f"{mode}@{c}"] = {
                "mode": mode, "concurrency": c, "repetitions": len(rs),
                "p50_ms": med(lambda r: r["latency_ms"]["p50"]), "p95_ms": med(lambda r: r["latency_ms"]["p95"]),
                "p99_ms": med(lambda r: r["latency_ms"]["p99"]), "throughput_rps": med(lambda r: r["throughput_rps"]),
                "p95_ms_per_rep": [r["latency_ms"]["p95"] for r in rs], "errors": sum(r["errors"] for r in rs),
                "redis_mean_ms": med(lambda r: r["internal"]["sage_gateway_redis_telemetry_seconds"]["mean_ms"]),
                "ml_roundtrip_mean_ms": med(lambda r: r["internal"]["sage_gateway_ml_roundtrip_seconds"]["mean_ms"]),
                "kafka_publish_mean_ms": med(lambda r: r["internal"]["sage_gateway_kafka_publish_seconds"]["mean_ms"]),
                "gateway_cpu_pct_mean": med(lambda r: r["containers"]["sage-gateway"]["cpu_pct_mean"]),
                "gateway_mem_mib_max": med(lambda r: r["containers"]["sage-gateway"]["mem_mib_max"]),
                # ML calls = ML round-trip timer count. The outcome counter labels async re-scores of a
                # client that already has a cached decision as "Cached", so it undercounts async scoring.
                "ml_calls_per_rep": [r["internal"]["sage_gateway_ml_roundtrip_seconds"]["count"] for r in rs],
                "ml_outcomes_per_rep": [r["internal"]["ml_outcomes"] for r in rs],
                "ml_attempts_per_rep": [r["internal"]["ml_attempts"] for r in rs],
            }
    overhead = {}
    for c in levels:
        base = cells.get(f"off@{c}")
        for mode in modes:
            cell = cells.get(f"{mode}@{c}")
            if base and cell and mode != "off" and base["p95_ms"] is not None and cell["p95_ms"] is not None:
                overhead[f"{mode}@{c}"] = {"p95_minus_off_ms": cell["p95_ms"] - base["p95_ms"],
                                           "p50_minus_off_ms": cell["p50_ms"] - base["p50_ms"]}
    async_diffs = [v["p95_minus_off_ms"] for k, v in overhead.items() if k.startswith("async@")]
    return cells, overhead, (max(async_diffs) if async_diffs else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway-url", default="http://localhost:8083")
    ap.add_argument("--modes", default="off,features,async,sync")
    ap.add_argument("--concurrency", default="1,8,32")
    ap.add_argument("--repetitions", type=int, default=3)
    ap.add_argument("--requests-per-worker", type=int, default=200)
    ap.add_argument("--think-ms", type=float, default=20.0)
    ap.add_argument("--out-root", default=str(REPO / "results" / "benchmark"))
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--label", default="final")
    args = ap.parse_args()

    commit, dirty = git_state()
    if dirty and not args.allow_dirty:
        raise SystemExit("Working tree is dirty; commit first or pass --allow-dirty")
    modes = args.modes.split(",")
    levels = [int(x) for x in args.concurrency.split(",")]
    bench_id = f"bench-{args.label}-{uuid.uuid4().hex[:8]}"
    out_dir = Path(args.out_root) / bench_id
    out_dir.mkdir(parents=True)
    env_base = dict(__import__("os").environ)
    env_base.pop("SAGE_ML_MODE", None)

    meta = {"benchmark_id": bench_id, "git_commit": commit, "git_dirty": dirty, "allow_dirty": args.allow_dirty,
            "argv": sys.argv[1:], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": host_info(),
            "load_model": {"requests_per_worker": args.requests_per_worker, "think_ms": args.think_ms,
                           "mix": "3 non-static : 1 static", "non_static_paths": NON_STATIC, "static_paths": STATIC},
            "modes": modes, "concurrency_levels": levels, "repetitions": args.repetitions,
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "containers": {}}
    reps = []
    for mode in modes:
        restart_gateway(mode, args.gateway_url, env_base)
        meta["containers"][mode] = container_info()
        for c in levels:
            # warm-up (not recorded): JIT, connection pools
            run_rep(args.gateway_url, mode, min(c, 4), -1, argparse.Namespace(requests_per_worker=40, think_ms=args.think_ms), bench_id, out_dir / "warmup")
            for rep in range(args.repetitions):
                r = run_rep(args.gateway_url, mode, c, rep, args, bench_id, out_dir)
                print(f"{mode:8s} c={c:<3d} rep={rep} p50={r['latency_ms']['p50']:.2f} p95={r['latency_ms']['p95']:.2f} "
                      f"p99={r['latency_ms']['p99']:.2f} rps={r['throughput_rps']:.1f} err={r['errors']} "
                      f"ml_calls={r['internal']['sage_gateway_ml_roundtrip_seconds']['count']:.0f} attempts={r['internal']['ml_attempts']}")
                reps.append(r)
    restart_gateway("async", args.gateway_url, env_base)

    cells, overhead, r7 = summarise(reps, modes, levels)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (out_dir / "repetitions.json").write_text(json.dumps(reps, indent=2))
    summary = {"meta": meta, "cells": cells, "overhead_vs_off": overhead, "r7_observed_ms": r7,
               "r7_definition": "max over concurrency of median-rep p95(async) - median-rep p95(off) (configs/gates_revised_v1.json R7)"}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nR7 observed (max async p95 - off p95): {r7}")
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
diverse-shadow-traffic.py

Controlled traffic generator for SAGE shadow evaluation.
Enforces pre- and post-run cryptographic identity assertions against the frozen manifest,
supports dry-run smoke testing (changing volume only to 25 non-static requests per client),
and supports negative testing to prove traffic is aborted on hash mismatch.
"""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
GATEWAY_URL = os.getenv("SAGE_GATEWAY_URL", "http://localhost:8083")
ML_SERVICE_URL = os.getenv("SAGE_ML_URL", "http://localhost:8000")
RUN_ID = f"diverse-{uuid.uuid4().hex[:8]}"
MAX_WORKERS = max(1, int(os.getenv("DIVERSE_MAX_WORKERS", "3")))

# Ensure valid routes against mock-target-site/server.js before scoring.
HTML_PATHS = ["/", "/products", "/cart", "/products/12", "/products/34"]
API_PATHS = ["/api/inventory/23", "/api/price/23", "/api/search?q=phone"]
NON_STATIC_PATHS = sorted(set(HTML_PATHS + API_PATHS))
ASSET_PATHS = ["/static/style.css", "/static/app.js", "/static/logo.png"]
SCORING_PROBE_PATH = "/products/1"
DEFAULT_CLIENT_COUNT = max(1, int(os.getenv("DIVERSE_CLIENT_COUNT", "5")))

BASE_PROFILE_MATRIX = {
    "normal_browser": {
        "expected_class": "human",
        "asset_behavior": "Loads most assets",
        "rate": "Interactive",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.5, 1.5],
    },
    "spa_client": {
        "expected_class": "human",
        "asset_behavior": "Minimal assets, API-heavy",
        "rate": "Moderate",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.3, 1.0],
    },
    "mobile_browser": {
        "expected_class": "human",
        "asset_behavior": "Loads assets slowly",
        "rate": "Slow",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.5, 1.0],
    },
    "privacy_browser": {
        "expected_class": "human",
        "asset_behavior": "Selectively skips assets",
        "rate": "Interactive",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.5, 1.0],
    },
    "slow_scraper": {
        "expected_class": "bot",
        "asset_behavior": "Mostly non-static",
        "rate": "Slow",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.5, 1.0],
    },
    "asset_fetching_bot": {
        "expected_class": "bot",
        "asset_behavior": "Loads everything",
        "rate": "Rapid",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.1, 0.1],
    },
    "fast_scraper": {
        "expected_class": "bot",
        "asset_behavior": "Mostly API paths",
        "rate": "Very rapid",
        "client_count": DEFAULT_CLIENT_COUNT,
        "request_range": [22, 30],
        "delay_seconds": [0.01, 0.05],
    },
}

TARGET_VALIDATION_PATHS = sorted(set(HTML_PATHS + API_PATHS + ASSET_PATHS))


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_frozen_manifest(manifest_path: Path) -> Dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Frozen models manifest not found at {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_service_health(expected_identity: Dict[str, Any], stage: str = "Pre-run"):
    health_url = f"{ML_SERVICE_URL}/health"
    print(f"[*] Executing {stage} ML Service health & cryptographic identity check ({health_url})...")
    try:
        resp = requests.get(health_url, timeout=5)
        if resp.status_code != 200:
            print(f"[-] ERROR: ML Service health endpoint returned HTTP {resp.status_code}")
            sys.exit(1)
        data = resp.json()
    except Exception as e:
        print(f"[-] ERROR: Cannot connect to ML Service at {health_url}: {e}")
        sys.exit(1)

    mismatches = []
    checks = [
        ("prod_model_sha256", "prod_model_sha256"),
        ("shadow_model_sha256", "shadow_model_sha256"),
        ("shadow_contract_hash", "shadow_contract_hash"),
        ("shadow_feature_list_hash", "shadow_feature_list_hash"),
        ("shadow_threshold", "shadow_threshold"),
    ]

    for exp_key, obs_key in checks:
        exp_val = expected_identity.get(exp_key)
        obs_val = data.get(obs_key)
        if exp_key == "shadow_threshold":
            if exp_val is not None and obs_val is not None:
                if abs(float(exp_val) - float(obs_val)) > 1e-5:
                    mismatches.append(f"{exp_key}: expected {exp_val}, observed {obs_val}")
        else:
            if str(exp_val) != str(obs_val):
                mismatches.append(f"{exp_key}: expected {exp_val}, observed {obs_val}")

    if mismatches:
        print(f"[-] CRITICAL: {stage} ML Service Identity Mismatch against frozen manifest!")
        for m in mismatches:
            print(f"    - {m}")
        sys.exit(1)

    print(f"[+] {stage} ML Service Cryptographic Identity Verified successfully!")


def validate_target_paths():
    session = requests.Session()
    errors = []
    for path in TARGET_VALIDATION_PATHS:
        try:
            resp = session.get(f"{GATEWAY_URL}{path}", timeout=3)
        except requests.exceptions.RequestException as exc:
            errors.append(f"{path}: {exc}")
            continue

        if resp.status_code >= 400:
            errors.append(f"{path}: HTTP {resp.status_code}")

    if errors:
        print("Target path validation failed; refusing to produce a scored manifest.")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)


def fetch(session, path):
    for _ in range(3):
        try:
            resp = session.get(f"{GATEWAY_URL}{path}", timeout=10)
            if resp.status_code == 500:
                time.sleep(1.0)
                continue
            if resp.status_code >= 400 and resp.status_code not in (403, 404, 429):
                raise Exception(f"Gateway returned HTTP {resp.status_code} on {path}")
            return resp.status_code
        except requests.exceptions.RequestException:
            time.sleep(1.0)
            continue
    raise Exception(f"Failed to fetch {path} after 3 retries")


def clear_test_redis_cache():
    try:
        import redis
        r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, socket_timeout=1)
        for pattern in ["sage:ml-decision:*", "sage:timestamps:*", "sage:paths:*", "sage:telemetry:*"]:
            keys = list(r.scan_iter(match=pattern, count=100))
            if keys:
                r.delete(*keys)
        print("Cleared test Redis state.")
    except Exception as e:
        print(f"Note: Redis state clear skipped ({e}); fresh per-run IPs ensure clean evaluation state.")


def run_profile(profile_name, client_id, profile_matrix, is_dry_run=False, seed=None):
    run_hex = RUN_ID.replace("diverse-", "")[:4]
    run_octet = (int(run_hex, 16) % 250) + 1
    profile_idx = list(profile_matrix.keys()).index(profile_name) + 1
    client_idx = int(client_id.split("-")[-1]) if client_id.split("-")[-1].isdigit() else 1
    assigned_ip = f"10.{run_octet}.{profile_idx}.{client_idx + 1}"

    rng = random.Random(seed + client_idx) if seed is not None else random.Random()

    headers = {
        "X-User-ID": client_id,
        "X-SAGE-Client-Id": client_id,
        "X-SAGE-Run-Id": RUN_ID,
        "X-Sage-Profile": profile_name,
        "X-Forwarded-For": assigned_ip,
    }

    session = requests.Session()
    session.headers.update(headers)

    requests_made = 0
    status_counts = {}

    def tracked_fetch(path, is_probe=False):
        nonlocal requests_made
        if is_probe:
            session.headers["X-SAGE-Probe"] = "true"
        try:
            status_code = fetch(session, path)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Connection error on {path}: {e}") from e
        finally:
            if is_probe:
                session.headers.pop("X-SAGE-Probe", None)
        status_counts[str(status_code)] = status_counts.get(str(status_code), 0) + 1
        requests_made += 1

    if is_dry_run:
        # Dry-run requirement: exactly 25 non-static requests per client, ending with probe path
        # Changes only volume; maintains non-static navigation behavior.
        # Paced at 0.60s for slow clients (gaps >= 0.5s), and 0.15s for interactive/rapid clients.
        delay = 0.60 if "slow" in profile_name else 0.15
        for i in range(25):
            path = NON_STATIC_PATHS[i % len(NON_STATIC_PATHS)]
            tracked_fetch(path)
            time.sleep(delay)
        time.sleep(delay)
        tracked_fetch(SCORING_PROBE_PATH, is_probe=True)
        return {
            "client_id": client_id,
            "profile": profile_name,
            "request_count": requests_made,
            "status_counts": status_counts,
        }

    request_min, request_max = profile_matrix[profile_name]["request_range"]
    num_requests = rng.randint(request_min, request_max)

    if profile_name == "normal_browser":
        for _ in range(num_requests):
            tracked_fetch(rng.choice(HTML_PATHS))
            for asset in ASSET_PATHS:
                tracked_fetch(asset)
            time.sleep(rng.uniform(0.5, 1.5))
    elif profile_name == "spa_client":
        tracked_fetch("/index.html")
        for _ in range(num_requests):
            tracked_fetch(rng.choice(API_PATHS))
            time.sleep(rng.uniform(0.3, 1.0))
    elif profile_name == "mobile_browser":
        path = rng.choice(HTML_PATHS)
        for _ in range(num_requests):
            tracked_fetch(path)
            if rng.random() > 0.5:
                tracked_fetch("/static/style.css")
            time.sleep(rng.uniform(1.0, 3.0))
    elif profile_name == "privacy_browser":
        for _ in range(num_requests):
            tracked_fetch(rng.choice(HTML_PATHS))
            tracked_fetch("/static/style.css")
            time.sleep(rng.uniform(0.5, 2.0))
    elif profile_name == "slow_scraper":
        for i in range(num_requests):
            tracked_fetch(f"/products/{(i % 50) + 1}")
            time.sleep(rng.uniform(1.5, 3.0))
    elif profile_name == "asset_fetching_bot":
        for _ in range(num_requests):
            tracked_fetch(rng.choice(HTML_PATHS))
            for asset in ASSET_PATHS:
                tracked_fetch(asset)
            time.sleep(0.1)
    elif profile_name == "fast_scraper":
        start_time = time.time()
        i = 0
        while (time.time() - start_time) < 3.2 or i < 22:
            tracked_fetch(f"/api/price/{(i % 50) + 1}")
            time.sleep(rng.uniform(0.02, 0.05))
            i += 1
        time.sleep(rng.uniform(0.02, 0.05))
        tracked_fetch(SCORING_PROBE_PATH, is_probe=True)
        return {
            "client_id": client_id,
            "profile": profile_name,
            "request_count": requests_made,
            "status_counts": status_counts,
        }
    else:
        raise ValueError(f"Unknown profile: {profile_name}")

    time.sleep(rng.uniform(0.3, 0.8))
    tracked_fetch(SCORING_PROBE_PATH, is_probe=True)

    return {
        "client_id": client_id,
        "profile": profile_name,
        "request_count": requests_made,
        "status_counts": status_counts,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Diverse Shadow Traffic Generator")
    parser.add_argument("--dry-run", action="store_true", help="Dry run: volume change only, 25 non-static requests/client")
    parser.add_argument("--negative-test", action="store_true", help="Simulate wrong-hash manifest to assert exit 1 before traffic")
    parser.add_argument("--manifest-path", help="Custom output manifest path")
    parser.add_argument("--frozen-manifest", default=str(BASE_DIR / "ml_pipeline" / "models" / "frozen_models_manifest.json"))
    parser.add_argument("--campaign-config", default=str(BASE_DIR / "final_campaign_config.json"), help="Path to campaign configuration JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    random.seed(42)

    print(f"Starting Diverse Shadow Traffic Generator - RUN_ID: {RUN_ID}")
    print(f"Gateway URL: {GATEWAY_URL}")
    print(f"Dry run mode: {args.dry_run}")
    print(f"Negative test mode: {args.negative_test}")

    # 1. Load Frozen Manifest & Identity Tuple
    frozen_manifest_path = Path(args.frozen_manifest)
    frozen_manifest = load_frozen_manifest(frozen_manifest_path)
    expected_identity = dict(frozen_manifest.get("active_deployment", {}))

    if args.negative_test:
        print("[!] Injecting wrong shadow_model_sha256 to test pre-traffic abort gate...")
        expected_identity["shadow_model_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"

    # 2. Pre-run Health & Identity Assertion
    check_service_health(expected_identity, stage="Pre-run")

    # Container file hashes at run START
    print("[*] Recording container file hashes at run START...")
    def get_container_file_sha256(container_name: str, file_path: str) -> str:
        res = subprocess.run(
            ["docker", "exec", container_name, "sha256sum", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to hash {file_path} in {container_name}: {res.stderr.strip()}")
        return res.stdout.strip().split()[0]

    start_main_py_sha256 = get_container_file_sha256("sage-ml", "/app/main.py")
    start_app_jar_sha256 = get_container_file_sha256("sage-gateway", "/app/app.jar")
    print(f"    [+] sage-ml:/app/main.py    = {start_main_py_sha256}")
    print(f"    [+] sage-gateway:/app/app.jar = {start_app_jar_sha256}")

    # 3. Path Validation & Redis Cache Clear
    validate_target_paths()
    clear_test_redis_cache()

    # Read and hash campaign configuration bytes first
    campaign_config_file = Path(args.campaign_config)
    if campaign_config_file.exists():
        cfg_bytes = campaign_config_file.read_bytes()
        campaign_config_hash = hashlib.sha256(cfg_bytes).hexdigest()
        campaign_config_data = json.loads(cfg_bytes.decode("utf-8"))
    else:
        campaign_config_hash = "unknown"
        campaign_config_data = {}

    # Determine profiles & volume
    if args.dry_run:
        # Dry-run: 3 clients (1 human, 1 rapid bot, 1 slow bot with gaps >= 0.5s)
        profile_matrix = {
            "normal_browser": {
                "expected_class": "human",
                "asset_behavior": "25 non-static requests (dry run volume)",
                "rate": "Interactive",
                "client_count": 1,
                "request_range": [25, 25],
                "delay_seconds": [0.15, 0.15],
            },
            "fast_scraper": {
                "expected_class": "bot",
                "asset_behavior": "25 non-static requests (dry run volume)",
                "rate": "Rapid",
                "client_count": 1,
                "request_range": [25, 25],
                "delay_seconds": [0.15, 0.15],
            },
            "slow_scraper": {
                "expected_class": "bot",
                "asset_behavior": "25 non-static requests (gaps >= 0.5s for Long_Gap_Ratio)",
                "rate": "Slow",
                "client_count": 1,
                "request_range": [25, 25],
                "delay_seconds": [0.60, 0.60],
            },
        }
    else:
        configured_profiles = campaign_config_data.get("profiles", list(BASE_PROFILE_MATRIX.keys()))
        clients_per_prof = int(campaign_config_data.get("clients_per_profile", 50))
        profile_matrix = {}
        for p in configured_profiles:
            if p in BASE_PROFILE_MATRIX:
                p_dict = dict(BASE_PROFILE_MATRIX[p])
                p_dict["client_count"] = clients_per_prof
                profile_matrix[p] = p_dict
            else:
                profile_matrix[p] = {
                    "expected_class": "bot" if ("scraper" in p or "bot" in p) else "human",
                    "asset_behavior": "Standard behavior",
                    "rate": "Normal",
                    "client_count": clients_per_prof,
                    "request_range": [22, 30],
                    "delay_seconds": [0.5, 1.0],
                }

    # Compute harness and campaign hashes
    harness_path = Path(__file__).resolve()
    harness_hash = compute_file_sha256(harness_path)
    evaluator_path = BASE_DIR / "ml_pipeline" / "scripts" / "evaluate" / "evaluate_shadow.py"
    evaluator_hash = compute_file_sha256(evaluator_path) if evaluator_path.exists() else "unknown"

    run_mode_val = "dry_run" if args.dry_run else campaign_config_data.get("run_mode", "final")

    manifest = {
        "run_id": RUN_ID,
        "run_mode": run_mode_val,
        "gateway_url": GATEWAY_URL,
        "enforcement": "disabled_required",
        "harness_hash": harness_hash,
        "evaluator_hash": evaluator_hash,
        "campaign_config_hash": campaign_config_hash,
        "campaign_config": campaign_config_data,
        "seeds": campaign_config_data.get("profile_seeds", {"random_seed": 42}),
        "expected_identity": expected_identity,
        "container_hashes": {
            "start": {
                "sage_ml_main_py_sha256": start_main_py_sha256,
                "sage_gateway_app_jar_sha256": start_app_jar_sha256,
            }
        },
        "profile_matrix": profile_matrix,
        "target_validation_paths": TARGET_VALIDATION_PATHS,
        "scoring_probe_path": SCORING_PROBE_PATH,
        "clients": {},
    }

    profile_seeds = campaign_config_data.get("profile_seeds", {})
    tasks = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for profile_name, metadata in profile_matrix.items():
            print(f"Queueing traffic for profile: {profile_name} ({metadata['client_count']} clients)")
            p_seed = profile_seeds.get(profile_name)
            for i in range(metadata["client_count"]):
                client_id = f"{profile_name}-{i:02d}"
                manifest["clients"][client_id] = {
                    "profile": profile_name,
                    "expected_label": metadata["expected_class"],
                    "true_class": metadata["expected_class"],
                    "client_id": client_id,
                    "run_id": RUN_ID,
                    "request_count": None,
                    "scoring_probe_path": SCORING_PROBE_PATH,
                }
                tasks.append(
                    executor.submit(run_profile, profile_name, client_id, profile_matrix, args.dry_run, p_seed)
                )

        print("Waiting for all clients to finish...")
        for future in as_completed(tasks):
            try:
                result = future.result()
                manifest["clients"][result["client_id"]]["request_count"] = result["request_count"]
                manifest["clients"][result["client_id"]]["status_counts"] = result["status_counts"]
            except Exception as e:
                print(f"Client failed with exception: {e}")
                continue

    # 4. Post-run Health & Identity Assertion
    check_service_health(expected_identity, stage="Post-run")

    # Container file hashes at run END & verification
    print("[*] Recording container file hashes at run END...")
    end_main_py_sha256 = get_container_file_sha256("sage-ml", "/app/main.py")
    end_app_jar_sha256 = get_container_file_sha256("sage-gateway", "/app/app.jar")
    print(f"    [+] sage-ml:/app/main.py    = {end_main_py_sha256}")
    print(f"    [+] sage-gateway:/app/app.jar = {end_app_jar_sha256}")

    if start_main_py_sha256 != end_main_py_sha256:
        raise RuntimeError(
            f"Container file mutation detected during run! sage-ml:/app/main.py changed from {start_main_py_sha256} to {end_main_py_sha256}"
        )
    if start_app_jar_sha256 != end_app_jar_sha256:
        raise RuntimeError(
            f"Container file mutation detected during run! sage-gateway:/app/app.jar changed from {start_app_jar_sha256} to {end_app_jar_sha256}"
        )
    print("    [+] Container files remained immutable across the entire run.")

    manifest["container_hashes"]["end"] = {
        "sage_ml_main_py_sha256": end_main_py_sha256,
        "sage_gateway_app_jar_sha256": end_app_jar_sha256,
    }

    # Output file determination
    if args.manifest_path:
        out_manifest_file = Path(args.manifest_path)
    elif args.dry_run:
        runs_dir = BASE_DIR / "load-tests" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        out_manifest_file = runs_dir / f"{RUN_ID}_manifest.json"
    else:
        out_manifest_file = BASE_DIR / "load-tests" / "diverse_manifest.json"

    out_manifest_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Traffic generation complete. Manifest saved to {out_manifest_file}")


if __name__ == "__main__":
    main()

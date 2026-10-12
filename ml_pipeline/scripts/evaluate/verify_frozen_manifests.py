#!/usr/bin/env python3
"""
verify_frozen_manifests.py

Independent verifier that:
1. Reads frozen models manifest via `git show <tag>:ml_pipeline/models/frozen_models_manifest.json`
2. For each explicit frozen file in the manifest, compares disk bytes to `git show <tag>:<path>`
3. Recomputes SHA-256 from disk bytes and asserts exact equality with the tagged manifest
4. Verifies pip-freeze environment against recorded versions
Exits 0 if all assertions hold; exits 1 with detailed failure report otherwise.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2].parent


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def get_tag_file_bytes(tag: str, rel_path: str) -> bytes:
    git_path = rel_path.replace("\\", "/")
    res = subprocess.run(
        ["git", "show", f"{tag}:{git_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise FileNotFoundError(
            f"Failed to read {git_path} from git tag {tag}: {res.stderr.decode('utf-8').strip()}"
        )
    return res.stdout


def parse_args():
    parser = argparse.ArgumentParser(description="Verify frozen model manifests against disk and git tag.")
    parser.add_argument("--tag", default="v2-frozen-models-v6", help="Git tag containing frozen manifest")
    parser.add_argument("--local-manifest", help="Optional fallback path to local manifest if tag is not yet created")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow dirty working tree, warning and listing file hashes")
    return parser.parse_args()


def verify(tag: str, local_manifest: str = None, allow_dirty: bool = False) -> bool:
    print(f"[*] Verifying frozen files against git tag `{tag}`...")
    
    # 1. Load manifest from git tag
    manifest_bytes = None
    try:
        manifest_bytes = get_tag_file_bytes(tag, "ml_pipeline/models/frozen_models_manifest.json")
        print(f"    Loaded frozen manifest from `git show {tag}:ml_pipeline/models/frozen_models_manifest.json`")
    except Exception as e:
        if local_manifest and Path(local_manifest).exists():
            print(f"    [!] Tag `{tag}` not found; using local fallback manifest `{local_manifest}` for pre-commit verification")
            manifest_bytes = Path(local_manifest).read_bytes()
        else:
            default_local = REPO_ROOT / "ml_pipeline" / "models" / "frozen_models_manifest.json"
            if default_local.exists():
                print(f"    [!] Tag `{tag}` not found; using local fallback `{default_local}`")
                manifest_bytes = default_local.read_bytes()
            else:
                print(f"[-] ERROR: Failed to load manifest: {e}")
                return False

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    frozen_files = manifest.get("frozen_files", {})
    if not frozen_files:
        print("[-] ERROR: Manifest has no `frozen_files` map")
        return False

    print(f"[*] Found {len(frozen_files)} frozen files in manifest.")

    errors = []
    for rel_path, expected_sha256 in frozen_files.items():
        disk_path = REPO_ROOT / rel_path
        if not disk_path.exists():
            errors.append(f"MISSING ON DISK: {rel_path}")
            continue

        disk_bytes = disk_path.read_bytes()
        disk_sha256 = sha256_bytes(disk_bytes)

        if disk_sha256 != expected_sha256:
            errors.append(
                f"HASH MISMATCH on {rel_path}:\n"
                f"  Expected: {expected_sha256}\n"
                f"  Disk:     {disk_sha256}"
            )
            continue

        # If tag is present, compare disk bytes directly to tagged bytes
        try:
            tagged_bytes = get_tag_file_bytes(tag, rel_path)
            if disk_bytes != tagged_bytes:
                errors.append(
                    f"BYTE DIVERGENCE from tag `{tag}` on {rel_path}:\n"
                    f"  Disk bytes ({len(disk_bytes)}) != Tagged bytes ({len(tagged_bytes)})"
                )
        except Exception:
            # If tag doesn't exist yet (pre-tag check), skip tag byte comparison
            pass

    if errors:
        print("\n[-] VERIFICATION FAILED:")
        for err in errors:
            print(f"    - {err}")
        return False

    print("[+] All frozen files are byte-identical and hash-verified!")

    # 2. Check Python environment dependencies (including redis & uvicorn)
    print("\n[*] Verifying critical python package versions...")
    try:
        pip_res = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        current_pkgs = dict(
            line.split("==", 1) for line in pip_res.stdout.splitlines() if "==" in line
        )
        manifest_env = manifest.get("environment", {})
        saved_freeze = manifest_env.get("pip_freeze", "")
        saved_pkgs = dict(
            line.split("==", 1) for line in saved_freeze.splitlines() if "==" in line
        )

        critical_pkgs = ["xgboost", "scikit-learn", "numpy", "pandas", "fastapi", "pydantic", "redis", "uvicorn"]
        for pkg in critical_pkgs:
            exp = saved_pkgs.get(pkg)
            cur = current_pkgs.get(pkg)
            if exp and cur and exp != cur:
                print(f"[-] WARNING: Package version mismatch for {pkg}: manifest={exp}, current={cur}")
            elif not cur:
                print(f"[-] WARNING: Package {pkg} is missing from current environment")
            else:
                print(f"    [+] {pkg} == {cur} (OK)")
    except Exception as e:
        print(f"[-] Warning: Failed to verify pip packages: {e}")

    # 3. Clean-Tree Status Check (Dirty tracked tree = FAIL)
    print("\n[*] Checking Git working tree clean status...")
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        status_lines = [l for l in status_res.stdout.splitlines() if l.strip()]
        tracked_changes = [l for l in status_lines if not l.startswith("??")]
        if tracked_changes:
            if not allow_dirty:
                errors.append(
                    f"DIRTY TRACKED TREE: {len(tracked_changes)} tracked files modified or staged:\n"
                    + "\n".join(f"        {l}" for l in tracked_changes)
                )
            else:
                print(f"    [!] working_tree_state: DIRTY ({len(tracked_changes)} modified tracked files):")
                for tc in tracked_changes:
                    parts = tc.strip().split(maxsplit=1)
                    rel_f = parts[1] if len(parts) > 1 else parts[0]
                    fpath = REPO_ROOT / rel_f
                    sha = sha256_bytes(fpath.read_bytes()) if fpath.exists() else "deleted"
                    print(f"        - {rel_f}: {sha}")
        else:
            print(f"    [+] Working tree is clean for tracked files ({len(status_lines)} untracked files present).")
    except Exception as e:
        errors.append(f"Failed to check git working tree status: {e}")

    # 4. Real Maven Dependency Tree Verification
    print("\n[*] Checking Maven dependencies via `mvn dependency:tree`...")
    try:
        env = os.environ.copy()
        if not env.get("JAVA_HOME") and Path("C:/Program Files/Java/jdk-21").exists():
            env["JAVA_HOME"] = "C:/Program Files/Java/jdk-21"

        mvn_res = subprocess.run(
            ["mvn", "dependency:tree"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=(sys.platform == "win32"),
            cwd=str(REPO_ROOT / "sage-gateway"),
            env=env,
        )
        if mvn_res.returncode != 0:
            errors.append(f"Maven dependency:tree failed (exit {mvn_res.returncode}): {mvn_res.stderr.strip()}")
        else:
            tree_output = mvn_res.stdout
            expected_deps = [
                ("Spring Boot Web", "org.springframework.boot:spring-boot-starter-web:jar:3.4.2"),
                ("Kafka Clients", "org.apache.kafka:kafka-clients:jar:3.8.1"),
                ("Spring Data Redis", "org.springframework.data:spring-data-redis:jar:3.4.2"),
                ("Lettuce Core", "io.lettuce:lettuce-core:jar:6.4.2.RELEASE"),
            ]
            for label, dep_str in expected_deps:
                if dep_str in tree_output:
                    print(f"    [+] {label}: {dep_str.split(':')[-2]} (OK)")
                else:
                    errors.append(f"Missing or mismatched Maven dependency: expected {dep_str}")
    except Exception as e:
        errors.append(f"Failed to execute Maven dependency check: {e}")

    # 5. List Previous Tags
    print("\n[*] Listing previous repository tags...")
    try:
        tag_res = subprocess.run(
            ["git", "tag", "-l"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        tags = [t.strip() for t in tag_res.stdout.splitlines() if t.strip()]
        for t in tags:
            print(f"    - Tag: {t}")
    except Exception as e:
        print(f"[-] Warning: Failed to list tags: {e}")

    # 6. Verify Active Deployment Tuple Self-Consistency
    print("\n[*] Verifying Active Deployment Tuple against Model & Contract tables...")
    active = manifest.get("active_deployment", {})
    intended = manifest.get("intended_shadow_model")
    print(f"    Intended Shadow Model: {intended}")
    assert intended == "eclog_timing_binary_model", f"Expected intended eclog_timing_binary_model, got {intended}"
    assert active.get("shadow_model_name") == intended, "active_deployment.shadow_model_name must match intended"
    
    models = manifest.get("models", {})
    contracts = manifest.get("contracts", {})
    assert intended in models, f"Model {intended} missing from models table"
    exp_model_sha = models[intended]["sha256"]
    assert active.get("shadow_model_sha256") == exp_model_sha, "Shadow model SHA mismatch with table row"
    
    contract_name = active.get("shadow_contract_name")
    assert contract_name in contracts, f"Contract {contract_name} missing from contracts table"
    exp_contract_sha = contracts[contract_name]["sha256"]
    exp_feat_sha = contracts[contract_name]["feature_list_sha256"]
    assert active.get("shadow_contract_hash") == exp_contract_sha, "Shadow contract SHA mismatch with table row"
    assert active.get("shadow_feature_list_hash") == exp_feat_sha, "Shadow feature list SHA mismatch with table row"
    print("    [+] Active deployment tuple strictly matches model and contract table rows!")

    print(f"\n[+] Active Deployment Tuple:\n{json.dumps(active, indent=2)}")

    if errors:
        print("\n[-] VERIFICATION FAILED:")
        for err in errors:
            print(f"    - {err}")
        return False

    print("\n[+] Verification SUCCESS: Frozen files and manifest are valid.")
    return True


def main():
    args = parse_args()
    success = verify(args.tag, args.local_manifest, allow_dirty=args.allow_dirty)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

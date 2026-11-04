"""
Campaign C must use the same 7 profiles as runs A/B. This test replays every profile through the
current generator and through run B's harness (git 6f432ba, SHA-256 9643c558…, recorded in run B's
manifest) with network and sleep stubbed, and requires identical request paths, sleep durations and
client IPs for the same seeds. Only the probe headers may differ.
"""

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUN_B_HARNESS_REV = "6f432ba"
RUN_B_HARNESS_SHA256 = "9643c5581423272ed1f5482636a06dc0308c7a32bad5e7f8c73769a089dec11f"
PROFILE_SEEDS = {"normal_browser": 9101, "spa_client": 9102, "mobile_browser": 9103, "privacy_browser": 9104,
                 "slow_scraper": 9105, "asset_fetching_bot": 9106, "fast_scraper": 9107}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def harnesses(tmp_path_factory):
    try:
        src = subprocess.run(["git", "show", f"{RUN_B_HARNESS_REV}:load-tests/diverse-shadow-traffic.py"],
                             cwd=REPO, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git history with run B harness not available")
    assert hashlib.sha256(src).hexdigest() == RUN_B_HARNESS_SHA256
    old_path = tmp_path_factory.mktemp("runb") / "harness_run_b.py"
    old_path.write_bytes(src)
    return _load(old_path, "harness_run_b"), _load(REPO / "load-tests" / "diverse-shadow-traffic.py", "harness_now")


def _trace(mod, profile, client_idx, monkeypatch):
    calls = []
    clock = {"t": 0.0}

    def fake_fetch(session, path):
        calls.append(("GET", path, session.headers.get("X-Forwarded-For")))
        return 200

    def fake_sleep(s):
        calls.append(("SLEEP", round(s, 12)))
        clock["t"] += s

    monkeypatch.setattr(mod, "fetch", fake_fetch)
    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(mod, "RUN_ID", "diverse-abcd1234")
    client_id = f"{profile}-{client_idx:02d}"
    result = mod.run_profile(profile, client_id, mod.BASE_PROFILE_MATRIX, False, PROFILE_SEEDS[profile])
    return calls, result["request_count"]


@pytest.mark.parametrize("profile", list(PROFILE_SEEDS))
@pytest.mark.parametrize("client_idx", [0, 1, 37, 74])
def test_profile_traffic_identical_to_run_b(harnesses, profile, client_idx, monkeypatch):
    old, new = harnesses
    assert _trace(new, profile, client_idx, monkeypatch) == _trace(old, profile, client_idx, monkeypatch)

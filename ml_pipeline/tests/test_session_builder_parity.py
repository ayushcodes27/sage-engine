"""
build_eclog_sessions.py on the one-day EClog must reproduce the committed training table
eclog_weak_labeled.csv exactly. Needs the Dataverse file ml_pipeline/data/eclog_1day.csv (guestbook-gated,
not committed); skipped when it is absent.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "ml_pipeline" / "data" / "eclog_1day.csv"


@pytest.mark.skipif(not RAW.exists(), reason="eclog_1day.csv not downloaded (see configs/datasets.json)")
def test_one_day_sessions_match_committed_training_table(tmp_path):
    out = tmp_path / "eclog1d_sessions.csv.gz"
    subprocess.run([sys.executable, str(REPO / "ml_pipeline/scripts/train/build_eclog_sessions.py"),
                    "--input", str(RAW), "--out", str(out), "--workers", "2"], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(REPO / "ml_pipeline/scripts/evaluate/check_session_builder_parity.py"),
                        str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]

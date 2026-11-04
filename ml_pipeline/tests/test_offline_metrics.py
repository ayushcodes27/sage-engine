"""Client aggregation and the validation threshold rule of configs/offline_protocol_v1.json."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml_pipeline" / "scripts" / "evaluate"))
from offline_metrics import client_table, confusion, threshold_at_fpr  # noqa: E402


def test_threshold_allows_at_most_max_fpr_and_excludes_ties():
    humans = [0.9, 0.8, 0.8, 0.5] + [0.1] * 96  # N = 100, 1 % -> one false positive allowed
    t = threshold_at_fpr(humans, 0.01)
    assert sum(h >= t for h in humans) == 1 and 0.8 < t <= 0.9
    assert sum(h >= threshold_at_fpr(humans, 0.0) for h in humans) == 0


def test_client_max_score_and_mixed_clients_excluded():
    s = pd.DataFrame({"IpId": ["a", "a", "b", "c", "c"], "label": ["bot", "bot", "human", "bot", "human"]})
    clients, mixed = client_table(s, [0.2, 0.7, 0.4, 0.9, 0.1])
    assert mixed == 1
    assert clients.set_index("IpId")["score"].to_dict() == {"a": 0.7, "b": 0.4}
    assert confusion(clients["y"], clients["score"], 0.5) == {"tp": 1, "fn": 0, "fp": 0, "tn": 1}

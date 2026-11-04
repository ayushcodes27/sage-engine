"""The traffic generator's pre/post-run identity check covers additional shadow models (audit N25)."""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("diverse_traffic", REPO / "load-tests" / "diverse-shadow-traffic.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

BASE = {"prod_model_sha256": "p", "shadow_model_sha256": "s", "shadow_contract_hash": "c",
        "shadow_feature_list_hash": "f", "shadow_threshold": 0.35}
EXTRA = {"name": "m7", "sha256": "x", "contract_hash": "xc", "feature_list_hash": "xf", "threshold": 0.0176}


class Resp:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def health(extra):
    return {"prod_model_sha256": "p", "shadow_model_sha256": "s", "shadow_contract_hash": "c",
            "shadow_feature_list_hash": "f", "shadow_threshold": 0.35, "extra_shadows": extra}


def check(monkeypatch, expected, observed_extra):
    monkeypatch.setattr(gen.requests, "get", lambda *a, **k: Resp(health(observed_extra)))
    gen.check_service_health(expected, stage="test")


def test_matching_extra_shadow_passes(monkeypatch):
    check(monkeypatch, {**BASE, "extra_shadows": [EXTRA]}, [dict(EXTRA)])


def test_no_extras_expected_and_none_running_passes(monkeypatch):
    check(monkeypatch, BASE, [])


@pytest.mark.parametrize("observed", [
    [],                                               # expected model not running
    [{**EXTRA, "sha256": "other"}],                   # different model file
    [{**EXTRA, "threshold": 0.35}],                   # different threshold
    [dict(EXTRA), {**EXTRA, "name": "unexpected"}],   # an unlisted extra model is running
])
def test_extra_shadow_mismatch_aborts(monkeypatch, observed):
    with pytest.raises(SystemExit):
        check(monkeypatch, {**BASE, "extra_shadows": [EXTRA]}, observed)


def test_unexpected_extra_when_none_declared_aborts(monkeypatch):
    with pytest.raises(SystemExit):
        check(monkeypatch, BASE, [dict(EXTRA)])

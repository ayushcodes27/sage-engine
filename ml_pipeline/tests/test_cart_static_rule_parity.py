"""
Regression test: the gateway's default cart and static-asset rules must equal the
EClog training rule in label_eclog.py. Adding "basket" to the gateway default
(commit 2d063bd) changed SAGE_Cart_Ratio for both frozen models; this test fails on that.
"""

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "scripts" / "train"))
from label_eclog import CART_KEYWORDS, STATIC_ASSET_EXTS  # noqa: E402

APPLICATION_YAML = BASE_DIR / "sage-gateway" / "src" / "main" / "resources" / "application.yaml"
REDIS_SERVICE = (
    BASE_DIR / "sage-gateway" / "src" / "main" / "java" / "com" / "sage" / "gateway"
    / "service" / "RedisTelemetryService.java"
)


def _yaml_default(key):
    text = APPLICATION_YAML.read_text(encoding="utf-8")
    match = re.search(rf"{key}:\s*\$\{{[A-Z_]+:([^}}]*)\}}", text)
    assert match, f"{key} default not found in application.yaml"
    return {v.strip() for v in match.group(1).split(",") if v.strip()}


def test_yaml_cart_default_matches_training_rule():
    assert _yaml_default("cart-keywords") == set(CART_KEYWORDS)


def test_yaml_static_default_matches_training_rule():
    assert _yaml_default("static-extensions") == {e.lstrip(".") for e in STATIC_ASSET_EXTS}


def test_java_cart_constants_match_training_rule():
    src = REDIS_SERVICE.read_text(encoding="utf-8")
    const = re.search(r'DEFAULT_CART_KEYWORDS\s*=\s*"([^"]*)"', src)
    assert const, "DEFAULT_CART_KEYWORDS constant not found"
    assert set(const.group(1).split(",")) == set(CART_KEYWORDS)

    static_rule = re.search(r'isCartPath\(String canonicalPath\)\s*\{.*?matches\("\.\*\(([^)]*)\)\.\*"\)', src, re.S)
    assert static_rule, "isCartPath regex not found"
    assert set(static_rule.group(1).split("|")) == set(CART_KEYWORDS)

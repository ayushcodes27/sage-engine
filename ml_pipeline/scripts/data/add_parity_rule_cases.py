#!/usr/bin/env python3
"""
Adds cart/static rule cases to the shared feature-parity fixture.

Expected values are computed with the EClog training rule (label_eclog.py via the
Python parity implementation in tests/test_feature_parity.py); the Java gateway must
reproduce them independently in CrossLanguageParityTest. Existing cases are left as-is.
Idempotent: cases already present (by case_id) are replaced with freshly computed values.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
FIXTURE = BASE_DIR / "ml_pipeline" / "models" / "fixtures" / "feature_parity_golden.json"
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "tests"))
sys.path.insert(0, str(BASE_DIR / "ml_pipeline" / "scripts" / "train"))
from test_feature_parity import calculate_python_pipeline_features  # noqa: E402


def req(ts, raw_path):
    return {"timestamp_ms": ts, "path": raw_path.split("?")[0], "raw_path": raw_path}


NEW_CASES = [
    {
        "case_id": "basket_is_not_cart_under_eclog_rule",
        "description": "zanbil-style /basket path must NOT count as cart under the EClog training rule",
        "requests": [req(5_000_000, "/products/1"), req(5_001_000, "/basket/view"), req(5_002_000, "/basket/add?id=3")],
    },
    {
        "case_id": "query_string_static_and_cart",
        "description": "query strings are stripped before the static and cart rules",
        "requests": [
            req(6_000_000, "/home"),
            req(6_000_100, "/assets/app.js?v=12"),
            req(6_000_200, "/static/x?cache=1"),
            req(6_001_000, "/checkout?step=2"),
            req(6_002_500, "/home"),
        ],
    },
    {
        "case_id": "uppercase_paths_canonicalised",
        "description": "paths are lower-cased before the static and cart rules",
        "requests": [req(7_000_000, "/Shop/CART"), req(7_000_300, "/IMG/Logo.PNG"), req(7_001_200, "/Shop/Item/9")],
    },
]


def main():
    data = json.loads(FIXTURE.read_bytes().decode("utf-8"))
    keep = [c for c in data["cases"] if c["case_id"] not in {n["case_id"] for n in NEW_CASES}]
    for case in NEW_CASES:
        for r in case["requests"]:
            r.pop("is_static", None)
            r.pop("is_cart", None)
        case["eval_at_request"] = len(case["requests"])
        case["expected_features"] = calculate_python_pipeline_features(case["requests"], case["eval_at_request"])
        keep.append(case)
    data["cases"] = keep
    text = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", "\r\n")
    FIXTURE.write_bytes(text.encode("utf-8"))
    print(f"Fixture now has {len(keep)} cases -> {FIXTURE}")


if __name__ == "__main__":
    main()

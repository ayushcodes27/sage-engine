#!/usr/bin/env python3
"""
regrade_campaigns.py

Re-grades archived campaign runs from their raw telemetry. Writes a NEW report; the original run
reports (load-tests/final_campaign_report.md, load-tests/diverse_report.md) are not touched.

1. Original G1–G7: the evaluator pinned at tag v2-frozen-models-v6 (SHA-256 checked against the
   hash recorded in the run reports) is executed unchanged on each run; its gate lines are parsed.
2. Unified definitions (one rule for every run, see campaign_metrics.py) for G2/G5/G6.
3. Revised gates R1–R7 from configs/gates_revised_v1.json.
Metrics are reported for the 8-feature shadow model and the 7-feature production model.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_metrics as cm  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
TAG = "v2-frozen-models-v6"
ORIGINAL_EVALUATOR_SHA256 = "367cff60867249b109ddef302bab163179e5235eea46a80bc366bc925fffdf8d"
RUNS = {
    "A": {
        "run_id": "diverse-8881bc1c",
        "telemetry": "telemetry/diverse-8881bc1c/adversarial_retest_telemetry_8881bc1c.jsonl.gz",
        "manifest": "telemetry/diverse-8881bc1c/manifest_8881bc1c_reconstructed.json",
        "original_report": "load-tests/final_campaign_report.md",
    },
    "B": {
        "run_id": "diverse-ba1a90e8",
        "telemetry": "telemetry/diverse-ba1a90e8/diverse_telemetry_ba1a90e8.jsonl.gz",
        "manifest": "telemetry/diverse-ba1a90e8/manifest_ba1a90e8.json",
        "original_report": "load-tests/diverse_report.md",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_checksums(sums_file: Path):
    for line in sums_file.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        actual = sha256(sums_file.parent / name)
        if actual != digest:
            raise SystemExit(f"Checksum mismatch for {name}: expected {digest}, got {actual}")


def git_show(rev_path: str) -> bytes:
    return subprocess.run(["git", "show", rev_path], cwd=REPO, capture_output=True, check=True).stdout


def load_original_evaluator(workdir: Path):
    src = git_show(f"{TAG}:ml_pipeline/scripts/evaluate/evaluate_shadow.py")
    digest = hashlib.sha256(src).hexdigest()
    if digest != ORIGINAL_EVALUATOR_SHA256:
        raise SystemExit(f"Original evaluator hash {digest} != recorded {ORIGINAL_EVALUATOR_SHA256}")
    # The original computes REPO_ROOT as parents[3] of its own path, so mirror the repo layout.
    path = workdir / "ml_pipeline" / "scripts" / "evaluate" / "evaluate_shadow_original.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("evaluate_shadow_original", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def original_gates(mod, telemetry_gz: Path, manifest_path: Path, run_id: str, workdir: Path) -> dict:
    plain = workdir / f"{run_id}.jsonl"
    with gzip.open(telemetry_gz, "rb") as fin, open(plain, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    manifest, clients = mod.load_manifest(str(manifest_path))
    df = mod.load_telemetry(str(plain), run_id)
    frozen, frozen_sha, source = mod.load_tagged_frozen_manifest(TAG, None)
    report, passed = mod.build_report(manifest, clients, df, 1000, tag=TAG, frozen_manifest=frozen,
                                      frozen_manifest_sha256=frozen_sha, manifest_source=source)
    body = report.split("## Safety Gates", 1)[1]
    gates = []
    for line in body.splitlines():
        m = re.match(r"^(.*): (PASS|FAIL)$", line.strip())
        if m:
            gates.append({"gate": m.group(1), "pass": m.group(2) == "PASS"})
    if len(gates) != 7:
        raise SystemExit(f"Expected 7 original gates, parsed {len(gates)}")
    for i, g in enumerate(gates, 1):
        g["id"] = f"G{i}"
    return {"all_pass": passed, "gates": gates, "frozen_manifest_sha256": frozen_sha, "frozen_manifest_source": source}


def unified_gates(original_cfg: dict, metrics: dict) -> dict:
    th = original_cfg["gate_thresholds"]
    scorable = metrics["scorable_clients"]
    cov = metrics["scorable_and_scored_clients"] / scorable if scorable else None
    fpr = metrics["human_fpr"]
    macro = metrics["macro_bot_recall"]
    return {
        "G2u_coverage_scorable": {"observed": cov, "threshold": th["scoring_coverage_min"],
                                  "pass": cov is not None and cov >= th["scoring_coverage_min"]},
        "G5u_human_fpr_point": {"observed": fpr["point"], "threshold": th["human_fpr_limit"],
                                "pass": fpr["point"] is not None and fpr["point"] <= th["human_fpr_limit"],
                                "clopper_pearson": fpr},
        "G6u_macro_recall_all_clients": {"observed": macro, "threshold": th["macro_average_bot_recall_min"],
                                         "pass": macro is not None and macro >= th["macro_average_bot_recall_min"]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-json", default="results/regrade_runs_AB.json")
    ap.add_argument("--out-md", default="results/regrade_runs_AB.md")
    ap.add_argument("--gates", default="configs/gates_revised_v1.json")
    args = ap.parse_args()

    verify_checksums(REPO / "telemetry" / "SHA256SUMS")
    original_cfg_bytes = git_show(f"{TAG}:final_campaign_config.json")
    original_cfg = json.loads(original_cfg_bytes)
    frozen_manifest = json.loads(git_show(f"{TAG}:ml_pipeline/models/frozen_models_manifest.json"))
    expected_identity = frozen_manifest["active_deployment"]
    gates_path = REPO / args.gates
    gate_cfg = cm.load_gate_config(gates_path)

    out = {
        "generated_by": "ml_pipeline/scripts/evaluate/regrade_campaigns.py",
        "inputs": {
            "tag": TAG,
            "original_evaluator_sha256": ORIGINAL_EVALUATOR_SHA256,
            "original_gate_config_sha256": hashlib.sha256(original_cfg_bytes).hexdigest(),
            "revised_gate_config": args.gates,
            "revised_gate_config_sha256": sha256(gates_path),
            "campaign_metrics_sha256": sha256(Path(cm.__file__)),
            "regrade_script_sha256": sha256(Path(__file__)),
        },
        "runs": {},
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        original = load_original_evaluator(tmp)
        for label, spec in RUNS.items():
            tel, man = REPO / spec["telemetry"], REPO / spec["manifest"]
            manifest = json.loads(man.read_text(encoding="utf-8"))
            clients = {cid: {"profile": v["profile"], "true_class": v["true_class"]} for cid, v in manifest["clients"].items()}
            events = cm.load_events(tel, spec["run_id"])

            run = {
                "run_id": spec["run_id"],
                "telemetry": spec["telemetry"],
                "telemetry_sha256": sha256(tel),
                "manifest": spec["manifest"],
                "manifest_reconstructed": bool(manifest.get("reconstructed")),
                "events": len(events),
                "original_report": spec["original_report"],
                "original_gates": original_gates(original, tel, man, spec["run_id"], tmp),
                "models": {},
            }
            for model in cm.MODELS:
                rows = cm.client_table(events, clients, model)
                metrics = cm.model_metrics(rows)
                run["models"][model] = {
                    "metrics": metrics,
                    "unified_gates": unified_gates(original_cfg, metrics),
                    "unscored_clients": [
                        {k: r[k] for k in ("client_id", "profile", "max_depth", "events", "unscored_reason")}
                        for r in rows if not r["scored"]
                    ],
                }
            shadow = run["models"]["shadow_eclog_timing_8feat"]["metrics"]
            run["revised_gates"] = cm.revised_gates(gate_cfg, shadow, events, expected_identity, None)
            run["failure_records"] = cm.failure_records(events)
            out["runs"][label] = run

    out_json = REPO / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    (REPO / args.out_md).write_text(render_md(out), encoding="utf-8")
    print(f"Wrote {out_json} and {args.out_md}")


def pct(x):
    return "n/a" if x is None else f"{100 * x:.2f}%"


def render_md(out: dict) -> str:
    L = ["# Re-grade of campaign runs A and B (unified gate definitions)", "",
         f"Generated by `{out['generated_by']}` from archived raw telemetry (`telemetry/`, checksums verified).",
         "The original run reports are unchanged. Original G1–G7 are produced by the tag-pinned original evaluator "
         f"(SHA-256 `{out['inputs']['original_evaluator_sha256'][:16]}…`).", ""]
    for label, run in out["runs"].items():
        L += [f"## Run {label} — `{run['run_id']}`", "",
              f"Events: {run['events']}; manifest: `{run['manifest']}`"
              + (" (**reconstructed**, see telemetry/README.md)" if run["manifest_reconstructed"] else ""), "",
              "### Original G1–G7 (unchanged definitions)", "", "| Gate | Result |", "|---|---|"]
        L += [f"| {g['id']} {g['gate']} | {'PASS' if g['pass'] else 'FAIL'} |" for g in run["original_gates"]["gates"]]
        L += ["", f"Failure records (evaluationStatus Timeout/SemaphoreFull/Error/Failed, shadow timeout/error, HTTP ≥ 500): "
              f"**{run['failure_records']}**", ""]
        for model, res in run["models"].items():
            m = res["metrics"]
            c = m["confusion"]
            f = m["human_fpr"]
            L += [f"### {model} — all manifest clients (unscored = not flagged)", "",
                  f"Confusion TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}; "
                  f"bot recall {pct(m['bot_recall']['point'])}; macro recall {pct(m['macro_bot_recall'])}; "
                  f"human FPR {pct(f['point'])} (95% CI {pct(f['lower'])}–{pct(f['upper'])}; one-sided 95% upper {pct(f['upper_one_sided'])}); "
                  f"scorable {m['scorable_clients']}, scored {m['scored_clients']}.", "",
                  "| Profile | Class | Clients | Scored | Flagged | Rate (all clients) | 95% CI | Rate (scored only) | Unscored reasons |",
                  "|---|---|---:|---:|---:|---:|---|---:|---|"]
            for p, pp in m["per_profile"].items():
                a, s = pp["all_clients"], pp["scored_only"]
                L.append(f"| {p} | {pp['true_class']} | {pp['clients']} | {pp['scored_clients']} | {pp['flagged']} | "
                         f"{pct(a['point'])} | {pct(a['lower'])}–{pct(a['upper'])} | {pct(s['point'])} | "
                         f"{', '.join(f'{k}: {v}' for k, v in pp['unscored_reasons'].items()) or '—'} |")
            L += ["", "| Unified gate | Observed | Threshold | Result |", "|---|---:|---:|---|"]
            for gname, g in res["unified_gates"].items():
                L.append(f"| {gname} | {pct(g['observed'])} | {pct(g['threshold'])} | {'PASS' if g['pass'] else 'FAIL'} |")
            L.append("")
        L += ["### Revised gates R1–R7 (8-feature shadow model)", "", "| Gate | Result | Observed |", "|---|---|---|"]
        for gname, g in run["revised_gates"].items():
            L.append(f"| {gname} | {'PASS' if g['pass'] else 'FAIL'} | `{json.dumps(g['observed'], default=str)[:160]}` |")
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Grades one campaign C run from its archived telemetry, exactly as declared in configs/campaign_c_declaration_v1.json.

  python grade_campaign_c.py --run-id R --telemetry T.jsonl.gz --manifest M.json --out results/campaign_c/R

* Original G1-G7: the tag-pinned original evaluator (regrade_campaigns.load_original_evaluator), unchanged.
* Unified definitions and revised gates R1-R7 (configs/gates_revised_v1.json) for every declared model/operating point:
  prod 7-feature, timing 8-feature shadow, v7 prefix @ frozen threshold, v7 prefix @ secondary (validation 0.1 % FPR).
* R7 comes from the canonical B2 benchmark summary (r7_observed_ms).
* Every unscored manifest client is listed with its telemetry-derived reason.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_metrics as cm  # noqa: E402
import regrade_campaigns as rg  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
DECL = REPO / "configs" / "campaign_c_declaration_v1.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--telemetry", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--benchmark", default="results/benchmark/bench-final-1971425f/summary.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    decl = json.loads(DECL.read_text())
    scoring = json.loads((REPO / "ml_pipeline/models/scoring_manifest_campaign_c_v1.json").read_text())["active_deployment"]
    (extra,) = scoring["extra_shadows"]
    name = extra["name"]
    secondary = decl["models_graded"][f"extra:{name}@secondary"]["threshold"]
    original_cfg = json.loads((REPO / "final_campaign_config.json").read_text())
    gate_cfg = cm.load_gate_config(REPO / "configs/gates_revised_v1.json")
    r7 = json.loads((REPO / args.benchmark).read_text())["r7_observed_ms"]

    tel, man = Path(args.telemetry), Path(args.manifest)
    manifest = json.loads(man.read_text())
    clients = {cid: {"profile": v["profile"], "true_class": v["true_class"]} for cid, v in manifest["clients"].items()}
    events = cm.load_events(tel, args.run_id)

    variants = {
        "prod_sage_binary_7feat": cm.MODELS["prod_sage_binary_7feat"],
        "shadow_eclog_timing_8feat": cm.MODELS["shadow_eclog_timing_8feat"],
        f"extra:{name}@frozen": cm.extra_model(name),
        f"extra:{name}@secondary": cm.extra_model(name, threshold=secondary),
    }
    out = {"run_id": args.run_id, "declaration_sha256": hashlib.sha256(DECL.read_bytes()).hexdigest(),
           "grader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "campaign_metrics_sha256": hashlib.sha256(Path(cm.__file__).read_bytes()).hexdigest(),
           "telemetry_sha256": hashlib.sha256(tel.read_bytes()).hexdigest(), "events": len(events),
           "clients": len(clients), "gateway_overhead_r7_ms": r7,
           "failure_records": cm.failure_records(events), "models": {}}
    with tempfile.TemporaryDirectory() as tmp:
        out["original_gates_timing_shadow"] = rg.original_gates(rg.load_original_evaluator(Path(tmp)), tel, man,
                                                                args.run_id, Path(tmp))
    for label, fns in variants.items():
        rows = cm.client_table(events, clients, fns)
        metrics = cm.model_metrics(rows)
        res = {"metrics": metrics, "unified_gates": rg.unified_gates(original_cfg, metrics),
               "unscored_clients": [{k: r[k] for k in ("client_id", "profile", "max_depth", "events", "unscored_reason")}
                                    for r in rows if not r["scored"]]}
        if label.startswith("extra:"):
            res["revised_gates"] = cm.revised_gates_extra(gate_cfg, metrics, events, name, extra, scoring, r7)
        elif label.startswith("shadow_"):
            res["revised_gates"] = cm.revised_gates(gate_cfg, metrics, events, scoring, r7)
        out["models"][label] = res

    d = Path(args.out)
    d.mkdir(parents=True, exist_ok=True)
    (d / "grade.json").write_text(json.dumps(out, indent=2) + "\n")
    (d / "report.md").write_text(render(out))
    print(f"wrote {d}/grade.json and report.md")
    for label, res in out["models"].items():
        m = res["metrics"]
        print(f"{label:40s} recall {m['bot_recall']['point']:.3f} macro {m['macro_bot_recall']:.3f} "
              f"FPR {m['human_fpr']['point']:.4f} (1-sided upper {m['human_fpr']['upper_one_sided']:.4f}) "
              f"unscored {len(res['unscored_clients'])}")
    print("original G1-G7:", "".join("P" if g["pass"] else "F" for g in out["original_gates_timing_shadow"]["gates"]))


def render(out):
    pct = rg.pct
    L = [f"# Campaign C grade - `{out['run_id']}`", "",
         f"Events {out['events']}, manifest clients {out['clients']}, failure records {out['failure_records']}, "
         f"R7 observed {out['gateway_overhead_r7_ms']} ms. Declaration sha256 `{out['declaration_sha256'][:16]}...`.", "",
         "## Original G1-G7 (timing shadow, unchanged evaluator)", "", "| Gate | Result |", "|---|---|"]
    L += [f"| {g['id']} {g['gate']} | {'PASS' if g['pass'] else 'FAIL'} |" for g in out["original_gates_timing_shadow"]["gates"]]
    for label, res in out["models"].items():
        m, c = res["metrics"], res["metrics"]["confusion"]
        f = m["human_fpr"]
        L += ["", f"## {label}", "",
              f"TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}; bot recall {pct(m['bot_recall']['point'])}; "
              f"macro recall {pct(m['macro_bot_recall'])}; human FPR {pct(f['point'])} "
              f"(95% CI {pct(f['lower'])}-{pct(f['upper'])}; one-sided upper {pct(f['upper_one_sided'])}); "
              f"scorable {m['scorable_clients']}, scored {m['scored_clients']}.", "",
              "| Profile | Class | Clients | Scored | Flagged | Rate (all) | 95% CI | Unscored reasons |",
              "|---|---|---:|---:|---:|---:|---|---|"]
        for p, pp in m["per_profile"].items():
            a = pp["all_clients"]
            L.append(f"| {p} | {pp['true_class']} | {pp['clients']} | {pp['scored_clients']} | {pp['flagged']} | "
                     f"{pct(a['point'])} | {pct(a['lower'])}-{pct(a['upper'])} | "
                     f"{', '.join(f'{k}: {v}' for k, v in pp['unscored_reasons'].items()) or '-'} |")
        if "revised_gates" in res:
            L += ["", "| Revised gate | Result | Observed |", "|---|---|---|"]
            L += [f"| {k} | {'PASS' if g['pass'] else 'FAIL'} | `{json.dumps(g['observed'], default=str)[:140]}` |"
                  for k, g in res["revised_gates"].items()]
        if res["unscored_clients"]:
            L += ["", f"Unscored clients ({len(res['unscored_clients'])}):", ""]
            L += [f"- `{u['client_id']}` ({u['profile']}): {u['unscored_reason']} (max depth {u['max_depth']:.0f}, {u['events']} events)"
                  for u in res["unscored_clients"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()

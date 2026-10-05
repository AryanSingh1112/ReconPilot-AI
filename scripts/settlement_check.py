"""python -m scripts.settlement_check
Rule-based layer: nothing is fitted, so no train/test split is needed. Parameters (tolerance, caps) were fixed beforehand."""
import json, time
import numpy as np, pandas as pd
from scipy.stats import beta
from reconpilot import config as C, settlement as ST


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, np.integer): return int(o)
    return o


pay = pd.read_parquet(C.DATA / "payments.parquet")
L = ST.Ledger(pay)
rows, lat = [], []
for r in L.rows:
    t0 = time.perf_counter()
    res = ST.reconcile_credit(L, r["batch_id"], r["credit"], "balanced")
    lat.append(time.perf_counter() - t0)
    rows.append({"truth": r["truth"], "detail": r["truth_detail"], "settle_day": r["settle_day"],
                 "statement": r["statement_total"], "variance": r["credit"] - r["statement_total"],
                 "action": res["action"], "rule": res["rule"], "kind": res["explanation"]["kind"],
                 "ids": res["explanation"]["payment_ids"], "n_solutions": res["explanation"]["n_solutions"]})
df = pd.DataFrame(rows)


def explained(r):
    if r.truth in ("missing_payment", "shifted_out"): return r.kind == "missing_payment" and r.ids == [r.detail]
    if r.truth == "shifted_in": return r.kind == "cross_batch" and r.ids == [r.detail]
    if r.truth == "extra_adjustment": return r.kind == "round_adjustment"
    return None


def summarize(d):
    auto = d.action == "AUTO_MATCH"
    should = d.truth.isin(["clean", "rounding"])
    k, na = int((auto & ~should).sum()), int(auto.sum())
    expl = {}
    for t in ("missing_payment", "shifted_out", "shifted_in", "extra_adjustment"):
        s = d[d.truth == t]
        ok = s.apply(explained, axis=1) if len(s) else pd.Series(dtype=bool)
        expl[t] = {"batches": int(len(s)), "correctly_explained": int(ok.sum()),
                   "ambiguous": int((s.kind == "ambiguous").sum()), "unexplained": int((s.kind == "none").sum()),
                   "wrongly_explained": int(((~ok) & (s.kind != "ambiguous") & (s.kind != "none")).sum())}
    bad = ~should
    return {"batches": int(len(d)), "auto_matched": na, "unsafe_auto_matches": k,
            "unsafe_rate_upper95": float(beta.ppf(0.975, k + 1, na - k)) if na > k else None,
            "straight_through_recall": float((auto & should).sum() / max(should.sum(), 1)),
            "variance_batches": int(bad.sum()), "variance_stopped_before_auto": int((bad & ~auto).sum()),
            "variance_amount_inr": float(d.variance[bad].abs().sum() / 100),
            "confusion": {str(a): {str(b): int(v) for b, v in row.items()} for a, row in pd.crosstab(d.truth, d.action).to_dict("index").items()},
            "explanation_accuracy": expl,
            "rule_counts": {str(a): int(b) for a, b in d.rule.value_counts().items()}}


out = {"note": "Deterministic layer on simulated credits; injected variances have known causes. No parameters were fitted.",
       "tolerance_inr": ST.TOL / 100, "batch_caps_inr": {k: v / 100 for k, v in ST.BATCH_CAP.items()},
       "all_batches": summarize(df), "test_period_batches": summarize(df[df.settle_day >= C.VALB_END]),
       "latency_ms": {"p50": float(np.percentile(lat, 50) * 1000), "p95": float(np.percentile(lat, 95) * 1000)}}
(C.ART / "eval_json").mkdir(parents=True, exist_ok=True)
(C.ART / "eval_json" / "settlement.json").write_text(json.dumps(clean(out), indent=2))
a = out["all_batches"]
print(f"batches={a['batches']} auto={a['auto_matched']} unsafe_auto={a['unsafe_auto_matches']} upper95={a['unsafe_rate_upper95']}")
print(f"straight-through recall={a['straight_through_recall']:.3f} variance batches={a['variance_batches']} stopped={a['variance_stopped_before_auto']}")
print("confusion:", a["confusion"])
print("explanations:", a["explanation_accuracy"])
print("latency ms:", out["latency_ms"])
"""python -m scripts.run_experiments            -> validation report (repeatable)
   python -m scripts.run_experiments --final    -> evaluates TEST once, then locks
   add --regen to rebuild the simulated data"""
import argparse, hashlib, json, subprocess, time
import joblib, numpy as np, pandas as pd, lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.calibration import calibration_curve
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from reconpilot import config as C, metrics as M
from reconpilot.baselines import exact_score, fuzzy_score
from reconpilot.features import History, pair_features
from reconpilot.pipeline import (anomaly_report, decide_all, decision_metrics, select_auto_threshold, top_table)
from reconpilot.simulator import generate

LOCK = C.ART / "test_eval.lock"
METHODS = ["exact", "fuzzy", "lr", "lgbm"]


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


def main(final, regen):
    if final and LOCK.exists():
        raise SystemExit("TEST SET ALREADY EVALUATED (artifacts/test_eval.lock). Refusing to evaluate again.")
    if regen and LOCK.exists():
        raise SystemExit("TEST SET ALREADY EVALUATED (artifacts/test_eval.lock). "
                         "Refusing to regenerate its data in this workspace.")
    for d in (C.DATA, C.ART / "eval_json", C.CHARTS, C.MODELS):
        d.mkdir(parents=True, exist_ok=True)
    ip, pp, lp, pf = (C.DATA / n for n in ("invoices.parquet", "payments.parquet", "lineage.parquet", "pairs.parquet"))
    if regen or not ip.exists():
        print("Generating simulated data...")
        inv, pay, lin = generate()
        inv.to_parquet(ip); pay.to_parquet(pp); lin.to_parquet(lp)
        if pf.exists(): pf.unlink()
    inv, pay, lin = pd.read_parquet(ip), pd.read_parquet(pp), pd.read_parquet(lp)
    truth = dict(zip(lin.payment_id, lin.true_invoice_id))
    inv_amount = dict(zip(inv.invoice_id, inv.amount))
    hist = History(pay)
    if not pf.exists():
        print("Generating candidates and features (1-3 minutes)...")
        pair_features(pay, inv, hist).to_parquet(pf)
    pairs = pd.read_parquet(pf)
    pay["day"] = pay.ts // C.DAY
    pairs["ts"] = pairs.payment_id.map(dict(zip(pay.payment_id, pay.ts)))
    pairs["y"] = (pairs.invoice_id == pairs.payment_id.map(truth)).astype(int)
    day = pairs.ts // C.DAY
    B = {"train": (0, C.TRAIN_END), "val_a": (C.TRAIN_END, C.VALA_END), "val_b": (C.VALA_END, C.VALB_END), "test": (C.VALB_END, 10**6)}
    pm = {k: ((day >= a) & (day < b)).to_numpy() for k, (a, b) in B.items()}
    qm = {k: ((pay.day >= a) & (pay.day < b)).to_numpy() for k, (a, b) in B.items()}
    assert pairs.ts[pm["train"]].max() < pairs.ts[pm["val_a"]].min() <= pairs.ts[pm["val_a"]].max() \
        < pairs.ts[pm["val_b"]].min() <= pairs.ts[pm["val_b"]].max() < pairs.ts[pm["test"]].min()
    X, y = pairs[C.FEATURES], pairs.y.to_numpy()
    print(f"payments={len(pay)} pairs={len(pairs)} positive_pairs={y.sum()} "
          f"train/val_a/val_b/test payments={[int(qm[k].sum()) for k in B]}")

    def fit_lgbm(feats, spw):
        m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=40,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, max_bin=63,
                               scale_pos_weight=spw, n_jobs=2, random_state=C.SEED, verbose=-1)
        return m.fit(pairs.loc[pm["train"], feats], y[pm["train"]])

    imb = {}
    for spw in (1, 3, 8):
        m = fit_lgbm(C.FEATURES, spw)
        imb[spw] = (m, average_precision_score(y[pm["val_a"]], m.predict_proba(X[pm["val_a"]])[:, 1]))
    best = max(imb, key=lambda k: imb[k][1]); gbm = imb[best][0]
    lr = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                       LogisticRegression(class_weight="balanced", max_iter=2000)).fit(X[pm["train"]], y[pm["train"]])
    raw = {"lr": lr.predict_proba(X)[:, 1], "lgbm": gbm.predict_proba(X)[:, 1]}
    cals = {n: M.SigmoidCalibrator().fit(raw[n][pm["val_a"]], y[pm["val_a"]]) for n in raw}
    scores = {"exact": exact_score(pairs), "fuzzy": fuzzy_score(pairs),
              "lr": cals["lr"].predict(raw["lr"]), "lgbm": cals["lgbm"].predict(raw["lgbm"])}

    th = {}
    vb_pay, vb_pairs = pay[qm["val_b"]], pairs[pm["val_b"]]
    for m in METHODS:
        th[m] = {}
        for p, prof in C.PROFILES.items():
            auto = select_auto_threshold(vb_pay, vb_pairs.assign(score=scores[m][pm["val_b"]]), truth, hist, prof)
            th[m][p] = {"review": C.REVIEW_THR, "auto": auto, "min_margin": prof["min_margin"], "cap": prof["cap"]}

    ablation = {"all_features": float(average_precision_score(y[pm["val_b"]], raw["lgbm"][pm["val_b"]]))}
    for gname, cols in C.GROUPS.items():
        feats = [f for f in C.FEATURES if f not in cols]
        m = fit_lgbm(feats, best)
        ablation[f"without_{gname}"] = float(average_precision_score(y[pm["val_b"]], m.predict_proba(X.loc[pm["val_b"], feats])[:, 1]))

    def evaluate(split):
        pp_, py, yy = pairs[pm[split]], pay[qm[split]], y[pm[split]]
        out = {"split": split, "n_payments": len(py), "n_pairs": len(pp_), "positive_pairs": int(yy.sum()),
               "methods": {}, "ablation_val_b_pr_auc": ablation, "imbalance_scale_pos_weight": best}
        decs = {}
        for m in METHODS:
            s = scores[m][pm[split]]
            dec = decide_all(py, pp_.assign(score=s), th[m]["balanced"], hist, inv_amount)
            decs[m] = dec
            t = top_table(py.set_index("payment_id", drop=False), pp_.assign(score=s))
            top1 = float((t.top_inv == pd.Series(truth).reindex(t.index)).sum() / len(py))
            out["methods"][m] = {"pair_pr_auc": float(average_precision_score(yy, s)),
                                 "pair_pr_auc_ci95": M.bootstrap_ci(yy, s), "pair_roc_auc": float(roc_auc_score(yy, s)),
                                 "top1_accuracy": top1, "thresholds": th[m]["balanced"],
                                 "decision": decision_metrics(dec, py, truth)}
        out["lgbm_minus_lr_pr_auc_ci95"] = M.paired_boot_diff(yy, scores["lgbm"][pm[split]], scores["lr"][pm[split]])
        out["calibration"] = {"brier_raw": float(brier_score_loss(yy, raw["lgbm"][pm[split]])),
                              "brier_calibrated": float(brier_score_loss(yy, scores["lgbm"][pm[split]])),
                              "ece_raw": M.ece(yy, raw["lgbm"][pm[split]]), "ece_calibrated": M.ece(yy, scores["lgbm"][pm[split]])}
        ranks = pp_[pp_.y == 1].cand_rank
        out["candidate_recall"] = {"at_limit": float(len(ranks) / len(py)),
                                   "curve": [float((ranks < k).sum() / len(py)) for k in range(1, C.CAND_LIMIT + 1)]}
        out["profiles"] = {p: decision_metrics(decide_all(py, pp_.assign(score=scores["lgbm"][pm[split]]), th["lgbm"][p],
                                                          hist, inv_amount), py, truth) for p in C.PROFILES}
        d = decs["lgbm"].merge(py[["payment_id", "is_duplicate", "short_settle", "ref_style"]], on="payment_id")
        d["true"] = d.payment_id.map(truth)
        out["slices_by_ref_style"] = {s: decision_metrics(decs["lgbm"][decs["lgbm"].payment_id.isin(d.payment_id[d.ref_style == s])],
                                                           py[py.ref_style == s], truth) for s in sorted(d.ref_style.unique())}
        causes = {"wrong_or_missing_link": d.assigned != d.true, "duplicate_payment": d.is_duplicate == 1,
                  "short_settlement": d.short_settle == 1}
        out["error_table"] = {k: {"payments": int(v.sum()), "stopped_before_auto_post": int((v & (d.action != "AUTO_MATCH")).sum()),
                                  "reached_auto_post": int((v & (d.action == "AUTO_MATCH")).sum())} for k, v in causes.items()}
        nd = py[py.is_duplicate == 0]; pn = pp_[pp_.payment_id.isin(nd.payment_id)].assign(score=scores["lgbm"][pm[split]][pairs[pm[split]].payment_id.isin(nd.payment_id).to_numpy()])
        hung = decide_all(nd, pn, th["lgbm"]["balanced"], hist, inv_amount, True).assigned
        greedy = decide_all(nd, pn, th["lgbm"]["balanced"], hist, inv_amount, False).assigned
        tr = nd.payment_id.map(truth).to_numpy()

        def shared(a): c = a.dropna().value_counts(); return int(c[c > 1].sum())
        out["assignment"] = {"greedy_top1_accuracy": float((greedy.to_numpy() == tr).mean()),
                             "hungarian_accuracy": float((hung.to_numpy() == tr).mean()),
                             "greedy_payments_sharing_an_invoice": shared(greedy),
                             "hungarian_payments_sharing_an_invoice": shared(hung)}
        out["anomaly_detection"] = anomaly_report(py, hist)
        t0 = time.perf_counter()
        pf_ = pair_features(py, inv, hist)
        sc = cals["lgbm"].predict(gbm.predict_proba(pf_[C.FEATURES])[:, 1])
        decide_all(py, pf_.assign(score=sc), th["lgbm"]["balanced"], hist, inv_amount)
        el = time.perf_counter() - t0
        out["throughput"] = {"payments": len(py), "seconds": el, "payments_per_minute": len(py) / el * 60}
        out["feature_importance_gain"] = dict(sorted(zip(C.FEATURES, (gbm.booster_.feature_importance("gain") /
                                                                      gbm.booster_.feature_importance("gain").sum()).tolist()), key=lambda x: -x[1]))
        return out

    def charts(split):
        pp_, yy = pairs[pm[split]], y[pm[split]]
        save = lambda n: (plt.savefig(C.CHARTS / n, dpi=110, bbox_inches="tight"), plt.close())
        plt.figure(figsize=(6, 4))
        for m in METHODS:
            pr, rc, _ = precision_recall_curve(yy, scores[m][pm[split]]); plt.plot(rc, pr, label=m)
        plt.xlabel("Recall"); plt.ylabel("Precision"); plt.title(f"Pair precision-recall ({split})"); plt.legend(); save("pr_curve.png")
        plt.figure(figsize=(5, 4))
        for name, s in (("raw", raw["lgbm"][pm[split]]), ("calibrated", scores["lgbm"][pm[split]])):
            fy, fx = calibration_curve(yy, s, n_bins=10, strategy="quantile"); plt.plot(fx, fy, marker="o", label=name)
        plt.plot([0, 1], [0, 1], "--", color="grey"); plt.xlabel("Predicted"); plt.ylabel("Observed"); plt.title(f"Calibration ({split})"); plt.legend(); save("calibration.png")
        py = pay[qm[split]]; t = top_table(py.set_index("payment_id", drop=False), pp_.assign(score=scores["lgbm"][pm[split]]))
        wrong = (t.top_inv != pd.Series(truth).reindex(t.index)).to_numpy(); mm = C.PROFILES["balanced"]["min_margin"]
        grid = np.linspace(0.2, 0.99, 40); ar, ir = [], []
        for g in grid:
            s = ((t.p1 >= g) & (t.margin >= mm)).to_numpy(); ar.append(s.sum() / len(py)); ir.append(wrong[s].mean() if s.any() else 0)
        plt.figure(figsize=(6, 4)); plt.plot(grid, ar, label="auto-match share"); plt.plot(grid, ir, label="wrong-link rate among auto")
        plt.axvline(th["lgbm"]["balanced"]["auto"], ls="--", color="grey"); plt.xlabel("Auto-match threshold"); plt.title(f"Threshold sweep, top-1 view ({split})"); plt.legend(); save("threshold_sweep.png")
        rk = pp_[pp_.y == 1].cand_rank; ks = range(1, C.CAND_LIMIT + 1)
        plt.figure(figsize=(5, 4)); plt.plot(list(ks), [(rk < k).sum() / int(qm[split].sum()) for k in ks], marker="o")
        plt.xlabel("Candidate limit"); plt.ylabel("Candidate recall"); plt.title(f"Candidate recall ({split})"); save("candidate_recall.png")
        imp = gbm.booster_.feature_importance("gain"); o = np.argsort(imp)[-12:]
        plt.figure(figsize=(6, 4)); plt.barh([C.FEATURES[i] for i in o], imp[o] / imp.sum()); plt.title("Feature importance (gain share)"); save("feature_importance.png")

    val = evaluate("val_b")
    (C.ART / "eval_json" / "validation.json").write_text(json.dumps(clean(val), indent=2))
    report, rsplit = val, "val_b"
    bundle = {"model": gbm, "calibrator": cals["lgbm"], "features": C.FEATURES, "thresholds": th["lgbm"], "version": "lgbm_match_v1"}
    joblib.dump(bundle, C.MODELS / "bundle.joblib")
    if final:
        report, rsplit = evaluate("test"), "test"
        (C.ART / "eval_json" / "test.json").write_text(json.dumps(clean(report), indent=2))
        LOCK.write_text(f"test evaluated {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    charts(rsplit)
    card = {"payments": len(pay), "invoices": len(inv), "pairs": len(pairs), "positive_pairs": int(y.sum()),
            "pair_positive_rate": float(y.mean()), "duplicates": int(pay.is_duplicate.sum()),
            "ref_style_counts": pay.ref_style.value_counts().to_dict(),
            "split_payments": {k: int(qm[k].sum()) for k in B},
            "split_days": {k: list(v) for k, v in B.items()}, "held_out_style": "spaced (test period only)",
            "data_sha256": sha(pp), "seed": C.SEED, "limitation": "Simulated data; not Razorpay, bank or UPI data."}
    (C.ART / "eval_json" / "dataset_card.json").write_text(json.dumps(clean(card), indent=2))
    try: commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception: commit = "n/a"
    (C.ART / "manifest.json").write_text(json.dumps(clean({"created": time.strftime("%Y-%m-%d %H:%M:%S"), "seed": C.SEED,
        "git_commit": commit, "bundle_sha256": sha(C.MODELS / "bundle.joblib"), "thresholds": th, "features": C.FEATURES}), indent=2))

    print(f"\n=== {rsplit.upper()} ===")
    for m, r in report["methods"].items():
        d = r["decision"]
        print(f"{m:6s} pairPR-AUC={r['pair_pr_auc']:.3f} top1={r['top1_accuracy']:.3f} auto={d['auto_rate']:.3f} "
              f"review={d['review_rate']:.3f} exc={d['exception_rate']:.3f} autoPrec={d['auto_precision']:.3f} "
              f"recall={d['straight_through_recall']:.3f} incorrectAuto={d['incorrect_auto_post_rate']:.4f}")
    print("candidate recall:", round(report["candidate_recall"]["at_limit"], 3), "| payments/min:", round(report["throughput"]["payments_per_minute"]))
    print("assignment:", report["assignment"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true"); ap.add_argument("--regen", action="store_true")
    a = ap.parse_args(); main(a.final, a.regen)
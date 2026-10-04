from datetime import datetime, timedelta
import joblib
import numpy as np
import pandas as pd
from . import config as C
from .baselines import exact_score
from .controls import settlement_checks
from .explain import build_evidence, explain
from .features import History, pair_features
from .pipeline import decide_all, pay_flags
from .policy import ACTION_TEXT, RULE_TEXT


class State:
    pass


def to_paise(x):
    value = float(x)
    if not np.isfinite(value):
        raise ValueError("Monetary values must be finite")
    paise = int(round(value * 100))
    if abs(paise) > C.MAX_SAFE_PAISE:
        raise ValueError("Monetary value exceeds the supported paise range")
    return paise


def default_payment_time():
    return (C.SIM_START + timedelta(days=C.VALB_END + 3, hours=10)).isoformat(timespec="minutes")


def load_state():
    S = State()
    S.inv = pd.read_parquet(C.DATA / "invoices.parquet")
    S.pay = pd.read_parquet(C.DATA / "payments.parquet")
    S.hist = History(S.pay)
    S.inv_amount = dict(zip(S.inv.invoice_id, S.inv.amount))
    S.inv_by_id = S.inv.set_index("invoice_id")
    bp = C.MODELS / "bundle.joblib"
    S.bundle = joblib.load(bp) if bp.exists() else None
    t = S.pay[S.pay.ts >= C.VALB_END * C.DAY]
    clean = (t.is_duplicate == 0) & (t.fee_anomaly == 0) & (t.short_settle == 0) & (t.delay_anomaly == 0)
    defs = [
        ("clean_exact", "Clean exact match", "Reference and amount match exactly.", clean & (t.ref_style == "clean") & (t.refund == 0)),
        ("fee_tax_refund", "Settlement with fee, tax and refund", "Net settlement equals payment minus fee, tax and refund.", clean & (t.refund > 0)),
        ("ambiguous", "Ambiguous narration", "Reference is truncated; several invoices may fit.", clean & (t.ref_style == "truncated")),
        ("missing_ref", "Missing reference", "No usable reference on the payment.", clean & (t.ref_style == "missing")),
        ("unseen_style", "Unseen reference format", "Reference format never seen in training.", clean & (t.ref_style == "spaced")),
        ("duplicate", "Duplicate payment", "Same payment received twice within a day.", t.is_duplicate == 1),
        ("unexpected_fee", "Unexpected fee", "Fee rate differs from the merchant's contract.", (t.fee_anomaly == 1) & (t.is_duplicate == 0)),
        ("short_settle", "Short settlement", "Observed net is below payment minus fee, tax and refund.", (t.short_settle == 1) & (t.is_duplicate == 0)),
        ("delayed", "Delayed settlement", "Payout arrived later than the merchant's usual window.", (t.delay_anomaly == 1) & (t.is_duplicate == 0)),
    ]
    S.scen = {sid: (title, desc, t[m]) for sid, title, desc, m in defs if m.any()}
    return S


def row_to_req(r):
    return {"payment_id": r.payment_id, "merchant_id": r.merchant_id, "customer_id": r.customer_id,
            "payer_name": r.payer_name, "amount": float(r.amount) / 100, "method": r.method,
            "payment_time": (C.SIM_START + timedelta(seconds=int(r.ts))).isoformat(),
            "reference": r.reference, "narration": r.narration, "fee": float(r.fee) / 100,
            "fee_tax": float(r.fee_tax) / 100, "refund": float(r.refund) / 100,
            "observed_net": float(r.observed_net) / 100, "settlement_lag_days": (r.settle_ts - r.ts) / C.DAY}


def scenario_request(S, sid, seed):
    df = S.scen[sid][2]
    return row_to_req(df.iloc[seed % len(df)])


def build_payment_row(req):
    cfg = C.MERCHANTS[req["merchant_id"]]
    amt = to_paise(req["amount"])
    t = req.get("payment_time")
    parsed_time = datetime.fromisoformat(t) if t else None
    if parsed_time is not None and parsed_time.utcoffset() is not None:
        raise ValueError("payment_time must be timezone-naive simulation-local ISO-8601")
    ts = int((parsed_time - C.SIM_START).total_seconds()) if parsed_time else (C.VALB_END + 3) * C.DAY
    if ts < 0: raise ValueError("payment_time is before the simulation start")
    fee = to_paise(req["fee"]) if req.get("fee") is not None else int(round(amt * cfg["fee_pct"]))
    tax = to_paise(req["fee_tax"]) if req.get("fee_tax") is not None else int(round(fee * C.TAX_RATE))
    refund = to_paise(req.get("refund") or 0)
    net = to_paise(req["observed_net"]) if req.get("observed_net") is not None else amt - fee - tax - refund
    lag = req.get("settlement_lag_days")
    lag = cfg["lag"] if lag is None else float(lag)
    if not np.isfinite(lag) or lag < 0 or lag > 36500:
        raise ValueError("settlement_lag_days must be finite and no greater than 36500")
    ref, payer = req.get("reference") or "", req.get("payer_name") or ""
    return pd.DataFrame([{
        "payment_id": req.get("payment_id") or "MANUAL", "merchant_id": req["merchant_id"],
        "customer_id": req.get("customer_id") or "", "payer_name": payer, "amount": amt, "ts": ts,
        "method": req.get("method", "upi"), "reference": ref,
        "narration": req.get("narration") or f"UPI/{ref or 'NOREF'}/{payer}",
        "fee": fee, "fee_tax": tax, "refund": refund, "observed_net": net, "settle_ts": ts + int(lag * C.DAY)}])


def reconcile_batch(S, reqs, profile=None, model_off=False):
    if not reqs:
        raise ValueError("No requests supplied")

    normalized = []
    for idx, original in enumerate(reqs):
        req = dict(original)
        if not req.get("payment_id"):
            req["payment_id"] = "MANUAL" if len(reqs) == 1 else f"BATCH-{idx + 1:06d}"
        normalized.append(req)
    payment_ids = [req["payment_id"] for req in normalized]
    if len(set(payment_ids)) != len(payment_ids):
        raise ValueError("payment_id values must be unique within a batch")

    profiles = {req.get("profile", profile or "balanced") for req in reqs}
    outage_modes = {bool(req.get("model_off", model_off)) for req in reqs}
    if len(profiles) != 1 or len(outage_modes) != 1:
        raise ValueError("All payments in a batch must use the same profile and model mode")
    prof = profiles.pop()
    if prof not in C.PROFILES:
        raise ValueError("unknown profile")
    model_loaded = S.bundle is not None
    outage_requested = outage_modes.pop()
    model_ok = model_loaded and not outage_requested
    model_mode = ("normal" if model_ok else "simulated_outage" if model_loaded
                  else "model_unavailable")
    th = S.bundle["thresholds"][prof] if model_ok else {
        **C.OUTAGE_TH, "cap": C.PROFILES[prof]["cap"]
    }

    batch = pd.concat([build_payment_row(req) for req in normalized], ignore_index=True)
    history = History(pd.concat([S.pay, batch], ignore_index=True))
    pairs = pair_features(batch, S.inv, history)
    if len(pairs):
        if model_ok:
            raw = S.bundle["model"].predict_proba(pairs[C.FEATURES])[:, 1]
            pairs["score"] = S.bundle["calibrator"].predict(raw)
        else:
            pairs["score"] = exact_score(pairs)
    else:
        pairs["score"] = pd.Series(dtype=float)

    decisions = decide_all(batch, pairs, th, history, S.inv_amount, use_assignment=True)
    decisions = decisions.set_index("payment_id")
    flags_by_id = pay_flags(batch, history)
    out = []
    for req in normalized:
        pid = req["payment_id"]
        payment = batch[batch.payment_id == pid]
        single_pairs = pairs[pairs.payment_id == pid]
        d = decisions.loc[pid]
        inv_id = d["assigned"] if isinstance(d["assigned"], str) else None
        r = payment.iloc[0]
        proof, checks, _ = settlement_checks(int(r.amount), int(r.fee), int(r.fee_tax), int(r.refund),
                                             int(r.observed_net), S.inv_amount.get(inv_id) if inv_id else None)
        fl = flags_by_id.loc[pid]
        proof_r = {k: (bool(v) if k in ("pass", "net_pass") else v / 100) for k, v in proof.items()}
        cands = []
        for c in single_pairs.sort_values("score", ascending=False).head(5).itertuples():
            iv = S.inv_by_id.loc[c.invoice_id]
            cands.append({"invoice_id": c.invoice_id, "customer": iv.customer_name, "amount": float(iv.amount) / 100,
                          "probability": float(c.score), "reference_match":
                          "Exact" if c.ref_digits_equal == 1 else ("Partial" if c.ref_prefix_frac > 0 or c.ref_sim > 0.6 else "None"),
                          "assigned": c.invoice_id == inv_id})
        evidence = []
        if model_ok and inv_id:
            sel = single_pairs[single_pairs.invoice_id == inv_id].iloc[[0]]
            contrib = S.bundle["model"].predict(sel[C.FEATURES], pred_contrib=True)[0]
            evidence = build_evidence(contrib, sel.iloc[0])
        flags = {"dup": bool(fl.dup), "fee_unusual": bool(fl.fee_unusual), "delay_unusual": bool(fl.delay_unusual)}
        exp = explain(d["action"], d["rule"], proof_r, float(d["p"]), float(d["margin"]), inv_id,
                      bool(fl.dq_ok), flags, model_mode)
        out.append({"action": d["action"], "action_text": ACTION_TEXT[d["action"]],
                    "rule": d["rule"], "rule_text": RULE_TEXT[d["rule"]],
                    "probability": float(d["p"]), "margin": float(d["margin"]), "assigned_invoice": inv_id,
                    "mode": model_mode, "profile": prof,
                    "thresholds": {k: v for k, v in th.items() if k in ("review", "auto", "min_margin", "cap")},
                    "proof": proof_r, "checks": checks, "candidates": cands, "evidence": evidence,
                    "explanation": exp, "flags": flags, "model": S.bundle["version"] if model_ok else "exact_rules_only",
                    "payment_id": pid, "amount": float(r.amount) / 100})
    return out[0] if len(out) == 1 else out


def reconcile_case(S, req):
    return reconcile_batch(S, [req], profile=req.get("profile", "balanced"), model_off=req.get("model_off", False))
import logging

import numpy as np
import pandas as pd
from . import config as C
from .assign import assign
from .controls import anomaly_flags, settlement_checks
from .features import digits
from .metrics import boot_mean
from .policy import decide

logger = logging.getLogger(__name__)


def top_table(pay, pairs):
    if len(pairs) == 0:
        return pd.DataFrame(columns=["top_inv", "p1", "p2", "margin"])
    s = pairs.sort_values(["payment_id", "score"], ascending=[True, False])
    rank = s.groupby("payment_id").cumcount()
    first, second = s[rank == 0].set_index("payment_id"), s[rank == 1].set_index("payment_id")
    t = pd.DataFrame({"top_inv": first["invoice_id"], "p1": first["score"]})
    t["p2"] = second["score"].reindex(t.index).fillna(0.0)
    t["margin"] = t.p1 - t.p2
    return t


def pay_flags(pay, hist):
    rows = []
    for r in pay.itertuples(index=False):
        dup = hist.is_dup(r.merchant_id, r.customer_id, r.payer_name, r.amount, r.reference, r.ts,
                          r.payment_id)
        a = anomaly_flags(r.merchant_id, r.amount, r.fee, (r.settle_ts - r.ts) / C.DAY)
        _, _, ok = settlement_checks(r.amount, r.fee, r.fee_tax, r.refund, r.observed_net)
        rows.append((r.payment_id, dup, a["fee_unusual"], a["delay_unusual"], len(digits(r.reference)) > 0, ok))
    return pd.DataFrame(rows, columns=["payment_id", "dup", "fee_unusual", "delay_unusual", "dq_ok",
                                       "settle_ok"]).set_index("payment_id")


def decide_all(pay, pairs, th, hist, inv_amount, use_assignment=True):
    pay = pay.set_index("payment_id", drop=False)
    t = top_table(pay, pairs).reindex(pay.index)
    fl = pay_flags(pay, hist)
    assigned, force = t["top_inv"].copy(), False
    if use_assignment and len(pairs):
        try:
            elig = pairs[pairs.payment_id.isin(fl.index[~fl.dup])].copy()
            elig["merchant_id"] = elig["payment_id"].map(pay["merchant_id"])
            amap = assign(elig, th["review"])
            assigned = pd.Series([amap.get(p) for p in pay.index], index=pay.index, dtype=object)
        except Exception:
            logger.exception("Global assignment failed; affected payments will be reviewed")
            force = True
    sc = dict(zip(zip(pairs.payment_id, pairs.invoice_id), pairs.score)) if len(pairs) else {}
    rows = []
    for rec in pay.to_dict("records"):
        pid = rec["payment_id"]
        inv = assigned.get(pid)
        inv = None if pd.isna(inv) else inv
        top = t.at[pid, "top_inv"]
        p = float(sc.get((pid, inv), 0.0)) if inv else 0.0
        if inv is None: margin = 0.0
        elif inv == top: margin = float(t.at[pid, "margin"])
        else: margin = p - float(t.at[pid, "p1"])
        _, _, ok = settlement_checks(rec["amount"], rec["fee"], rec["fee_tax"], rec["refund"],
                                     rec["observed_net"], inv_amount.get(inv) if inv else None)
        f = fl.loc[pid]
        partial = inv is not None and rec["amount"] < inv_amount.get(inv, 0) - C.NET_TOL
        action, rule = decide(p, margin, ok, bool(f.dup), bool(f.dq_ok), bool(f.fee_unusual or f.delay_unusual),
                              rec["amount"], th, inv is not None, force, partial)
        rows.append((pid, inv, p, margin, action, rule))
    return pd.DataFrame(rows, columns=["payment_id", "assigned", "p", "margin", "action", "rule"])


def select_auto_threshold(pay, pairs, truth, hist, prof):
    """Lowest auto threshold whose wrong-link rate (among payments that would reach auto) <= profile limit. Validation only."""
    pay = pay.set_index("payment_id", drop=False)
    d = top_table(pay, pairs).join(pay_flags(pay, hist))
    d["amount"] = pay.amount
    d["wrong"] = d.top_inv.ne(pd.Series(truth).reindex(d.index))
    ok = ((~d.dup) & d.settle_ok & d.dq_ok & ~(d.fee_unusual | d.delay_unusual)
          & (d.amount <= prof["cap"]) & (d.margin >= prof["min_margin"]))
    d = d[ok]
    for t in np.sort(d.p1.unique()):
        s = d[d.p1 >= t]
        if len(s) >= 20 and s.wrong.mean() <= prof["max_bad"]:
            return max(float(t), C.REVIEW_THR)
    return 1.01


def decision_metrics(dec, pay, truth):
    d = dec.set_index("payment_id").join(pay.set_index("payment_id")[["amount", "is_duplicate", "short_settle"]])
    d["true"] = pd.Series(truth).reindex(d.index).to_numpy()
    good_link = (d.assigned == d["true"])
    auto = d.action == "AUTO_MATCH"
    unsafe = auto & (~good_link | (d.is_duplicate == 1) | (d.short_settle == 1))
    good = auto & ~unsafe
    should = (d.is_duplicate == 0) & (d.short_settle == 0)
    n, na = len(d), int(auto.sum())
    prec = float(good.sum() / max(na, 1)); rec = float(good.sum() / max(should.sum(), 1))
    return {"n": n, "auto_rate": na / max(n, 1), "review_rate": float((d.action == "REVIEW").mean()),
            "exception_rate": float((d.action == "EXCEPTION").mean()),
            "auto_precision": prec, "auto_precision_ci95": boot_mean(good[auto].to_numpy()),
            "straight_through_recall": rec, "f1": 2 * prec * rec / max(prec + rec, 1e-9),
            "incorrect_auto_post_rate": float(unsafe.sum() / max(na, 1)),
            "unsafe_auto_posts": int(unsafe.sum()), "wrong_link_auto_posts": int((auto & ~good_link).sum()),
            "amount_in_exception_inr": float(d.amount[d.action == "EXCEPTION"].sum() / 100),
            "amount_in_review_inr": float(d.amount[d.action == "REVIEW"].sum() / 100),
            "manual_workload": int((d.action != "AUTO_MATCH").sum())}


def anomaly_report(py, hist):
    fl = pay_flags(py, hist).reindex(py.payment_id.values)

    def pr(pred, true):
        pred, true = np.asarray(pred, bool), np.asarray(true, bool)
        tp = (pred & true).sum()
        return {"precision": float(tp / max(pred.sum(), 1)), "recall": float(tp / max(true.sum(), 1)),
                "flagged": int(pred.sum()), "actual": int(true.sum())}
    return {"duplicate_payment": pr(fl.dup, py.is_duplicate == 1),
            "unusual_fee": pr(fl.fee_unusual, py.fee_anomaly == 1),
            "delayed_settlement": pr(fl.delay_unusual, py.delay_anomaly == 1),
            "short_settlement": pr(~fl.settle_ok.to_numpy(bool), py.short_settle == 1)}
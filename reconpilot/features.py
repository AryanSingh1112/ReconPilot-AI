"""Candidate generation + pair features. Uses only invoices issued <= payment time and strictly prior payments."""
import re
import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein
from . import config as C

METHOD = {"card": 0, "upi": 1, "netbanking": 2, "wallet": 3}


def norm(s): return re.sub(r"[^A-Z0-9]", "", str(s).upper())
def digits(s): return re.sub(r"\D", "", str(s))


class History:
    def __init__(self, pay):
        self.amt = {k: np.sort(v.to_numpy()) for k, v in pay.groupby(["merchant_id", "amount"])["ts"]}
        self.dup = {}
        for key, group in pay.groupby(["merchant_id", "customer_id", "payer_name", "amount", "reference"]):
            ordered = group.sort_values("ts", kind="stable")
            self.dup[key] = (ordered["ts"].to_numpy(), ordered["payment_id"].to_numpy())

    def count_amount(self, m, a, t, days=7):
        arr = self.amt.get((m, a))
        if arr is None: return 0
        return int(np.searchsorted(arr, t, "left") - np.searchsorted(arr, t - days * C.DAY, "left"))

    def is_dup(self, m, c, pn, a, ref, t, payment_id=None):
        match = self.dup.get((m, c, pn, a, ref))
        if match is None: return False
        timestamps, payment_ids = match
        start = np.searchsorted(timestamps, t - C.DAY, "left")
        end = np.searchsorted(timestamps, t, "right")
        return bool(np.any(payment_ids[start:end] != payment_id)) if payment_id is not None else end > start


def generate_candidates(pay, inv, limit=C.CAND_LIMIT):
    inv = inv.assign(digits=inv.invoice_id.str.replace(r"\D", "", regex=True))
    by = {m: g.reset_index(drop=True) for m, g in inv.groupby("merchant_id")}
    rows = []
    for r in pay.itertuples(index=False):
        g = by.get(r.merchant_id)
        if g is None: continue
        issue, amt = g.issue_ts.to_numpy(), g.amount.to_numpy()
        age = r.ts - issue
        ok = (age >= 0) & (age <= C.CAND_MAX_AGE_DAYS * C.DAY)
        diff = np.abs(amt - r.amount)
        by_amt = ok & (diff <= np.maximum(500, 0.01 * amt))
        d = digits(r.reference)
        by_ref = (ok & g.digits.str.startswith(d).to_numpy()) if len(d) >= 3 else np.zeros(len(g), bool)
        idx = np.flatnonzero(by_amt | by_ref)
        if idx.size == 0: continue
        order = np.lexsort((age[idx], diff[idx], ~by_ref[idx]))
        for rank, i in enumerate(idx[order][:limit]):
            rows.append((r.payment_id, g.invoice_id.iat[i], rank))
    return pd.DataFrame(rows, columns=["payment_id", "invoice_id", "cand_rank"])


def pair_features(pay, inv, hist, limit=C.CAND_LIMIT):
    cols = ["payment_id", "invoice_id", "cand_rank"] + C.FEATURES
    cand = generate_candidates(pay, inv, limit)
    if cand.empty:
        return pd.DataFrame(columns=cols)
    df = (cand.merge(pay.add_prefix("p_"), left_on="payment_id", right_on="p_payment_id")
              .merge(inv.add_prefix("i_"), left_on="invoice_id", right_on="i_invoice_id"))
    pa, ia = df.p_amount.to_numpy(), df.i_amount.to_numpy()
    df["amount_diff_abs"] = np.abs(pa - ia) / 100
    df["amount_diff_rel"] = np.abs(pa - ia) / ia
    df["amount_exact"] = (pa == ia).astype(float)
    pdg = [digits(x) for x in df.p_reference]
    idg = [digits(x) for x in df.i_invoice_id]
    inorm = [norm(x) for x in df.i_invoice_id]
    rnorm = [norm(x) for x in df.p_reference]
    nnorm = [norm(x) for x in df.p_narration]
    df["ref_present"] = [float(len(a) > 0) for a in pdg]
    df["ref_exact_full"] = [float(len(r) > 0 and i in r) for r, i in zip(rnorm, inorm)]
    df["ref_digits_equal"] = [float(len(a) > 0 and a == b) for a, b in zip(pdg, idg)]
    df["ref_prefix_frac"] = [len(a) / len(b) if (a and b.startswith(a)) else 0.0 for a, b in zip(pdg, idg)]
    df["ref_sim"] = [fuzz.ratio(a, b) / 100 if a else np.nan for a, b in zip(pdg, idg)]
    df["ref_edit_dist"] = [float(Levenshtein.distance(a, b)) if a else np.nan for a, b in zip(pdg, idg)]
    df["narr_sim"] = [fuzz.partial_ratio(i, n) / 100 for i, n in zip(inorm, nnorm)]
    df["name_sim"] = [fuzz.token_set_ratio(a, b.upper()) / 100 if a else np.nan
                      for a, b in zip(df.p_payer_name, df.i_customer_name)]
    known = (df.p_customer_id != "")
    df["customer_known"] = known.astype(float)
    df["customer_match"] = np.where(known, (df.p_customer_id == df.i_customer_id).astype(float), np.nan)
    df["days_invoice_to_payment"] = (df.p_ts - df.i_issue_ts) / C.DAY
    df["days_past_due"] = (df.p_ts - df.i_due_ts) / C.DAY
    df["method_code"] = df.p_method.map(METHOD).astype(float)
    df["amount_log"] = np.log1p(df.p_amount / 100)
    df["hour_of_day"] = ((df.p_ts // 3600) % 24).astype(float)
    g = df.groupby("payment_id")
    df["n_candidates"] = g["invoice_id"].transform("size").astype(float)
    df["n_cand_same_amount"] = g["amount_exact"].transform("sum")
    df["amount_rank"] = g["amount_diff_abs"].rank(method="min")
    df["ref_sim_rank"] = g["ref_sim"].rank(ascending=False, method="min")
    df["ref_sim_gap"] = df["ref_sim"] - g["ref_sim"].transform("max")
    df["same_amount_payments_7d"] = [float(hist.count_amount(m, a, t))
                                     for m, a, t in zip(df.p_merchant_id, df.p_amount, df.p_ts)]
    return df[cols]
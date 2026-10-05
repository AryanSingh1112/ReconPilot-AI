"""Grouped settlement reconciliation: one bank credit versus the payments it should contain.
Deterministic arithmetic and bounded search. No model and no randomness at decision time."""
from datetime import timedelta
from itertools import combinations
import numpy as np
import pandas as pd
from . import config as C
from .policy import ACTION_TEXT

TOL = C.NET_TOL                      # paise (Rs 1)
BATCH_CAP = {"fast_close": 100_000_000, "balanced": 50_000_000, "control_first": 20_000_000}  # paise
MAX_SUBSET = 3
MAX_POOL = 60
MAX_NEIGHBOUR_POOL = 300
NEIGHBOUR_DAYS = 3
ADJ_UNIT = 5000                      # Rs 50 in paise
SMALL_VARIANCE = 0.005               # 0.5% of the statement

RULE_TEXT = {
    "CREDIT_RECONCILED": "Bank credit equals the gateway statement and the contract arithmetic within tolerance.",
    "HIGH_VALUE_BATCH_REVIEW": "Reconciles, but the batch total is above the auto-post cap for this profile.",
    "SHORT_VS_CONTRACT_REVIEW": "Bank credit equals the gateway statement, but the statement is below contract arithmetic.",
    "MISSING_PAYMENT_LIKELY": "Credit is short by the net of specific payment(s) in this batch. A person must confirm.",
    "CROSS_BATCH_PAYMENT_LIKELY": "Credit is over by the net of a payment that belongs to a neighbouring batch.",
    "ROUND_ADJUSTMENT_LIKELY": "Variance is a round amount, consistent with a bank adjustment, hold or chargeback. Verify.",
    "AMBIGUOUS_EXPLANATION": "More than one combination of payments explains the variance. A person must choose.",
    "SMALL_UNEXPLAINED_VARIANCE": "Small variance and no explanation was found.",
    "LARGE_UNEXPLAINED_VARIANCE": "Variance is large and no explanation was found. Investigate.",
    "NO_CREDIT_RECEIVED": "No positive bank credit was received for this batch.",
    "EMPTY_BATCH": "The batch has no payments.",
}

SCENARIOS = {
    "clean": ("Clean settlement", "Credit equals the gateway statement and the contract arithmetic."),
    "rounding": ("Rounding difference", "Credit differs by under Rs 1, inside tolerance."),
    "missing_payment": ("Missing payment", "Credit is short by the net of one payment."),
    "shifted_out": ("Payment settled in the next batch", "One payment was paid out a day later."),
    "shifted_in": ("Payment from the previous batch", "Credit includes a payment from the previous day's batch."),
    "extra_adjustment": ("Round-amount deduction", "Credit is short by a round amount, such as a hold or chargeback."),
    "statement_short": ("Short versus contract", "Credit equals the statement, but a payment's net is below contract arithmetic."),
}


def _inr(v):
    return f"Rs {v / 100:,.2f}"


def _r2(v):
    return round(float(v) / 100, 2)


class Ledger:
    """Groups payments into settlement batches (merchant + settlement day) and builds the simulated bank credit."""

    def __init__(self, pay, inject=True, seed=C.SEED + 7):
        p = pay.copy()
        if "short_settle" not in p:
            p["short_settle"] = 0
        p["expected_net"] = p.amount - p.fee - p.fee_tax - p.refund
        p["sday"] = (p.settle_ts // C.DAY).astype(int)
        cols = ["payment_id", "merchant_id", "amount", "fee", "fee_tax", "refund", "observed_net", "expected_net", "short_settle"]
        self.members, self.rows = {}, []
        for (m, d), g in p.groupby(["merchant_id", "sday"], sort=True):
            bid = f"SB-{m}-D{int(d):03d}"
            self.members[bid] = g[cols].reset_index(drop=True)
            st = int(g.observed_net.sum())
            self.rows.append({"batch_id": bid, "merchant_id": m, "settle_day": int(d), "n_payments": int(len(g)),
                              "statement_total": st, "contract_total": int(g.expected_net.sum()),
                              "has_short": bool(g.short_settle.any()), "credit": st,
                              "truth": "statement_short" if bool(g.short_settle.any()) else "clean", "truth_detail": ""})
        if inject:
            self._inject(np.random.default_rng(seed))
        self.by_id = {r["batch_id"]: r for r in self.rows}
        self.by_merchant = {}
        for r in self.rows:
            self.by_merchant.setdefault(r["merchant_id"], []).append((r["settle_day"], r["batch_id"]))

    def _inject(self, rng):
        index = {(r["merchant_id"], r["settle_day"]): i for i, r in enumerate(self.rows)}
        used = set()
        for i, r in enumerate(self.rows):
            if r["has_short"] or i in used:
                continue
            g = self.members[r["batch_id"]]
            st, u = r["statement_total"], rng.random()
            if u < 0.08 and len(g) >= 2:
                k = int(rng.integers(0, len(g)))
                net = int(g.observed_net.iloc[k])
                if net > 0:
                    r.update(credit=st - net, truth="missing_payment", truth_detail=str(g.payment_id.iloc[k]))
            elif u < 0.14:
                opts = [a * 100 for a in (250, 500, 1000, 1500) if a * 100 <= 0.2 * st]
                if opts:
                    adj = int(rng.choice(opts))
                    r.update(credit=st - adj, truth="extra_adjustment", truth_detail=str(adj))
            elif u < 0.20:
                delta = int(rng.integers(1, 61)) * int(rng.choice([-1, 1]))
                r.update(credit=st + delta, truth="rounding")
            elif u < 0.26 and len(g) >= 2:
                j = index.get((r["merchant_id"], r["settle_day"] + 1))
                if j is not None and j not in used and not self.rows[j]["has_short"]:
                    k = int(rng.integers(0, len(g)))
                    net = int(g.observed_net.iloc[k])
                    if net > 0:
                        pid = str(g.payment_id.iloc[k])
                        r.update(credit=st - net, truth="shifted_out", truth_detail=pid)
                        self.rows[j].update(credit=self.rows[j]["statement_total"] + net, truth="shifted_in", truth_detail=pid)
                        used.update({i, j})

    def neighbours(self, bid):
        r = self.by_id[bid]
        out = [self.members[b] for d, b in self.by_merchant[r["merchant_id"]]
               if b != bid and abs(d - r["settle_day"]) <= NEIGHBOUR_DAYS]
        return pd.concat(out, ignore_index=True) if out else self.members[bid].iloc[0:0]

    def count(self, scenario):
        return sum(1 for r in self.rows if r["truth"] == scenario)

    def pick(self, scenario, seed=0):
        c = [r for r in self.rows if r["truth"] == scenario]
        return c[seed % len(c)] if c else None

    def batch_list(self, merchant_id):
        out = [{"batch_id": r["batch_id"], "settle_date": (C.SIM_START + timedelta(days=r["settle_day"])).date().isoformat(),
                "n_payments": r["n_payments"], "statement_total": _r2(r["statement_total"])}
               for r in self.rows if r["merchant_id"] == merchant_id]
        return sorted(out, key=lambda x: x["settle_date"], reverse=True)


def _subsets(nets, target, rmin, rmax):
    for r in range(rmin, rmax + 1):
        sols = [c for c in combinations(range(len(nets)), r) if abs(sum(nets[i] for i in c) - target) <= TOL]
        if sols:
            return r, sols
    return 0, []


def _round_adjust(d):
    delta = abs(d)
    k = int(round(delta / ADJ_UNIT))
    return k * ADJ_UNIT if k >= 1 and abs(delta - k * ADJ_UNIT) <= TOL else None


def _found(out, ids, r, sols, where, d_credit, cross=False):
    names = [[ids[i] for i in c] for c in sols]
    unique = len(sols) == 1
    out.update(kind=("cross_batch" if cross else "missing_payment") if unique else "ambiguous",
               payment_ids=names[0], n_solutions=len(sols), alternatives=names[:3], size=r)
    if unique:
        verb = "short" if d_credit < 0 else "over"
        out["message"] = (f"Credit is {verb} by {_inr(abs(d_credit))}, exactly the net of {', '.join(names[0])} "
                          f"({where}). A person must confirm.")
    else:
        out["message"] = (f"Credit is off by {_inr(abs(d_credit))}; {len(sols)} different combinations of {r} "
                          f"payment(s) explain it, so the cause cannot be identified automatically.")
    return out


def explain_variance(g, nb, d_credit):
    out = {"kind": "none", "payment_ids": [], "n_solutions": 0, "alternatives": [], "truncated": False,
           "message": "No variance beyond tolerance."}
    if abs(d_credit) <= TOL:
        return out
    if d_credit < 0:
        pool = g[g.observed_net > 0]
        ids, nets = pool.payment_id.tolist(), [int(x) for x in pool.observed_net]
        trunc = len(ids) > MAX_POOL
        out["truncated"] = trunc
        target = -d_credit
        r, sols = _subsets(nets, target, 1, 1)
        if sols:
            return _found(out, ids, r, sols, "within this batch", d_credit)
        adj = _round_adjust(d_credit)
        if adj is not None:
            out.update(kind="round_adjustment", message=f"Credit is short by {_inr(abs(d_credit))}, a round amount "
                       f"(about {_inr(adj)}), consistent with a hold, chargeback or bank adjustment. Verify with the bank.")
            return out
        r, sols = _subsets(nets, target, 2, 2 if trunc else MAX_SUBSET)
        if sols:
            return _found(out, ids, r, sols, "within this batch", d_credit)
    else:
        pool = nb[nb.observed_net > 0]
        trunc = len(pool) > MAX_NEIGHBOUR_POOL
        pool = pool.head(MAX_NEIGHBOUR_POOL)
        ids, nets = pool.payment_id.tolist(), [int(x) for x in pool.observed_net]
        out["truncated"] = trunc
        r, sols = _subsets(nets, d_credit, 1, 2)
        if sols:
            return _found(out, ids, r, sols, "belongs to a neighbouring batch", d_credit, cross=True)
        adj = _round_adjust(d_credit)
        if adj is not None:
            out.update(kind="round_adjustment", message=f"Credit is over by {_inr(abs(d_credit))}, a round amount "
                       f"(about {_inr(adj)}). Verify with the bank.")
            return out
    extra = " The search was limited to a bounded pool." if out["truncated"] else ""
    out["message"] = f"Variance of {_inr(abs(d_credit))} could not be explained by any payment combination.{extra}"
    return out


def decide_credit(n, credit, d_credit, d_stmt, statement, expl, profile):
    if n == 0:
        return "EXCEPTION", "EMPTY_BATCH"
    if credit <= 0:
        return "EXCEPTION", "NO_CREDIT_RECEIVED"
    if abs(d_credit) <= TOL:
        if abs(d_stmt) > TOL:
            return "REVIEW", "SHORT_VS_CONTRACT_REVIEW"
        if credit > BATCH_CAP[profile]:
            return "REVIEW", "HIGH_VALUE_BATCH_REVIEW"
        return "AUTO_MATCH", "CREDIT_RECONCILED"
    k = expl["kind"]
    if k == "ambiguous":
        return "REVIEW", "AMBIGUOUS_EXPLANATION"
    if k == "missing_payment":
        return "REVIEW", "MISSING_PAYMENT_LIKELY"
    if k == "cross_batch":
        return "REVIEW", "CROSS_BATCH_PAYMENT_LIKELY"
    if k == "round_adjustment":
        return "REVIEW", "ROUND_ADJUSTMENT_LIKELY"
    if abs(d_credit) <= SMALL_VARIANCE * max(statement, 1):
        return "REVIEW", "SMALL_UNEXPLAINED_VARIANCE"
    return "EXCEPTION", "LARGE_UNEXPLAINED_VARIANCE"


def reconcile_credit(L, batch_id, credit, profile="balanced"):
    if profile not in BATCH_CAP:
        raise ValueError("unknown profile")
    g, meta, credit = L.members[batch_id], L.by_id[batch_id], int(credit)
    gross, fees, tax, refunds = (int(g[c].sum()) for c in ("amount", "fee", "fee_tax", "refund"))
    contract, statement = int(g.expected_net.sum()), int(g.observed_net.sum())
    d_stmt, d_credit = statement - contract, credit - statement
    nb = L.neighbours(batch_id) if d_credit > TOL else g.iloc[0:0]
    expl = explain_variance(g, nb, d_credit)
    action, rule = decide_credit(len(g), credit, d_credit, d_stmt, statement, expl, profile)
    var = (g.observed_net - g.expected_net).astype(int)
    flagged = set(expl["payment_ids"])
    payments = [{"payment_id": str(r.payment_id), "amount": _r2(r.amount), "expected_net": _r2(r.expected_net),
                 "observed_net": _r2(r.observed_net), "variance": _r2(v), "short": bool(abs(v) > TOL),
                 "explained": str(r.payment_id) in flagged}
                for r, v in zip(g.itertuples(), var)][:200]
    short = [p for p in payments if p["short"]]
    summary = (f"Decision {action}: {RULE_TEXT[rule]} Bank credit {_inr(credit)} against gateway statement "
               f"{_inr(statement)} (difference {_inr(d_credit)}, tolerance {_inr(TOL)}). Gateway statement against "
               f"contract arithmetic differs by {_inr(d_stmt)}. {expl['message'] if expl['kind'] != 'none' else ''}").strip()
    return {
        "batch_id": batch_id, "merchant_id": meta["merchant_id"],
        "settle_date": (C.SIM_START + timedelta(days=meta["settle_day"])).date().isoformat(),
        "n_payments": int(len(g)), "action": action, "action_text": ACTION_TEXT[action], "rule": rule,
        "rule_text": RULE_TEXT[rule], "profile": profile,
        "thresholds": {"tolerance": _r2(TOL), "batch_cap": _r2(BATCH_CAP[profile])},
        "proof": {"gross": _r2(gross), "fees": _r2(fees), "tax": _r2(tax), "refunds": _r2(refunds),
                  "contract_net": _r2(contract), "statement_net": _r2(statement), "bank_credit": _r2(credit),
                  "statement_vs_contract": _r2(d_stmt), "credit_vs_statement": _r2(d_credit),
                  "statement_pass": abs(d_stmt) <= TOL, "credit_pass": abs(d_credit) <= TOL},
        "explanation": expl, "short_payments": short, "payments": payments,
        "summary": {"provider": "template", "text": summary}, "variance_paise": int(d_credit),
    }
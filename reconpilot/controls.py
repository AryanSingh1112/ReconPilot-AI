"""Deterministic financial controls. No model involved."""
from . import config as C


def settlement_checks(gross, fee, tax, refund, observed, inv_amount=None, tol=C.NET_TOL):
    expected = gross - fee - tax - refund
    diff = observed - expected
    checks = [
        {"id": "INV-1", "name": "Net = gross - fee - tax - refund", "pass": abs(diff) <= tol},
        {"id": "INV-5", "name": "Refund is between zero and gross", "pass": 0 <= refund <= gross},
        {"id": "INV-6", "name": "Fee and tax are not negative", "pass": fee >= 0 and tax >= 0},
        {"id": "INV-7", "name": "Total deductions do not exceed gross", "pass": fee + tax + refund <= gross},
        {"id": "INV-8", "name": "Observed net is nonnegative", "pass": observed >= 0},
    ]
    if inv_amount is not None:
        checks.append({"id": "INV-2", "name": "Payment does not exceed invoice balance",
                       "pass": gross <= inv_amount + tol})
    proof = {"gross": gross, "fee": fee, "tax": tax, "refund": refund, "expected_net": expected,
             "observed_net": observed, "difference": diff, "tolerance": tol,
             "net_pass": abs(diff) <= tol, "pass": all(c["pass"] for c in checks)}
    return proof, checks, all(c["pass"] for c in checks)


def anomaly_flags(merchant, amount, fee, lag_days):
    cfg = C.MERCHANTS[merchant]
    return {"fee_unusual": abs(fee / amount - cfg["fee_pct"]) > 0.005,
            "delay_unusual": lag_days > cfg["lag"] + 2.5}
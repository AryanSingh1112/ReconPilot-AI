"""Causal generator: invoice -> payment -> fee/tax/refund -> settlement, then reference corruption.
True links live in a separate lineage table and are never model inputs."""
import numpy as np
import pandas as pd
from . import config as C

FIRST = ["Aarav", "Vihaan", "Anaya", "Diya", "Rohan", "Isha", "Kabir", "Meera", "Arjun", "Saanvi",
         "Kiran", "Neha", "Rahul", "Priya", "Ishaan", "Tara"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Gupta", "Reddy", "Khan", "Singh", "Patel", "Mehta", "Das", "Joshi"]
STYLES = ["clean", "nodash_lower", "truncated", "prefix_noise", "typo", "missing"]
P_STYLE = [0.34, 0.14, 0.16, 0.14, 0.08, 0.14]
PRICE_POINTS = np.array([499, 999, 1499, 2499, 4999, 9999, 24999, 49999]) * 100
NARR = ["UPI/{ref}/{name}", "NEFT-{name}-{ref}", "{ref} PAYMENT {name}"]


def corrupt_ref(inv_id, style, rng):
    n = inv_id.split("-")[1]
    if style == "clean":
        return inv_id
    if style == "nodash_lower":
        return "inv" + n
    if style == "truncated":
        return "INV-" + n[:3]
    if style == "prefix_noise":
        return f"UPI/{inv_id}/OK"
    if style == "typo":
        i = int(rng.integers(0, 4)); s = list(n); s[i], s[i + 1] = s[i + 1], s[i]
        return "INV-" + "".join(s)
    if style == "spaced":                       # held-out style: only appears in the test period
        return f"REF {n[:2]} {n[2:]}"
    return ""


def name_variant(full, rng):
    f, l = full.split()
    r = rng.random()
    if r < 0.10: return ""
    if r < 0.50: return full.upper()
    if r < 0.70: return f"{f[0]} {l}".upper()
    if r < 0.85: return f"{l} {f}".upper()
    i = int(rng.integers(1, len(f)))
    return (f[:i] + f[i + 1:] + " " + l).upper()


def _payment(r, ts, cfg, rng):
    amt = r.amount + (int(rng.choice([-1, 1]) * rng.integers(1, 100)) if rng.random() < 0.05 else 0)
    fee_anom = rng.random() < 0.03
    fee = int(round(amt * cfg["fee_pct"] * (2.2 if fee_anom else 1.0)))
    tax = int(round(fee * C.TAX_RATE))
    refund = int(amt * rng.uniform(0.1, 0.5)) if rng.random() < 0.04 else 0
    lag = cfg["lag"] + int(rng.integers(0, 2))
    delay_anom = rng.random() < 0.03
    if delay_anom:
        lag += int(rng.integers(4, 8))
    net = amt - fee - tax - refund
    short = rng.random() < 0.02
    if short:
        net -= int(amt * 0.02) + int(rng.integers(200, 500))
    if ts >= C.VALB_END * C.DAY and rng.random() < 0.35:
        style = "spaced"
    else:
        style = str(rng.choice(STYLES, p=P_STYLE))
    ref = corrupt_ref(r.invoice_id, style, rng)
    payer = name_variant(r.customer_name, rng)
    narr = str(rng.choice(NARR)).format(ref=ref or "NOREF", name=payer)
    return dict(merchant_id=r.merchant_id,
                customer_id=r.customer_id if rng.random() < 0.85 else "",
                payer_name=payer, amount=int(amt), ts=int(ts),
                method=str(rng.choice(["card", "upi", "netbanking", "wallet"], p=[.35, .40, .15, .10])),
                reference=ref, narration=narr, fee=fee, fee_tax=tax, refund=refund, observed_net=int(net),
                settle_ts=int(ts + lag * C.DAY), ref_style=style, is_duplicate=0,
                fee_anomaly=int(fee_anom), short_settle=int(short), delay_anomaly=int(delay_anom),
                refund_after_settlement=int(refund > 0 and rng.random() < 0.5),
                true_invoice_id=r.invoice_id)


def generate(seed=C.SEED, days=C.N_DAYS):
    rng = np.random.default_rng(seed)
    horizon = days * C.DAY
    inv, n = [], 0
    for m, cfg in C.MERCHANTS.items():
        nc = cfg["customers"]
        names = [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(nc)]
        typ = np.exp(rng.normal(7.8, 0.9, nc)).astype(int) * 100
        rec = rng.random(nc) < 0.5
        for d in range(days):
            k = rng.poisson(cfg["rate"] * (2.0 if 40 <= d <= 42 else 1.0))
            for _ in range(k):
                c = int(rng.integers(0, nc)); u = rng.random()
                if rec[c] and u < 0.7: amt = int(typ[c])
                elif u < 0.85: amt = int(rng.choice(PRICE_POINTS))
                else: amt = int(np.exp(rng.normal(7.8, 0.9))) * 100
                ts = d * C.DAY + int(rng.integers(0, C.DAY)); n += 1
                inv.append((f"INV-{n:05d}", m, f"{m}-C{c:03d}", names[c], amt, ts, ts + 30 * C.DAY))
    inv = pd.DataFrame(inv, columns=["invoice_id", "merchant_id", "customer_id", "customer_name",
                                     "amount", "issue_ts", "due_ts"])
    pay = []
    for r in inv.itertuples(index=False):
        if rng.random() > 0.88:
            continue
        ts = r.issue_ts + int(rng.lognormal(1.6, 0.8) * C.DAY)
        if ts >= horizon:
            continue
        p = _payment(r, ts, C.MERCHANTS[r.merchant_id], rng)
        pay.append(p)
        if rng.random() < 0.02:
            dp = dict(p); dp["ts"] = ts + int(rng.integers(60, 3600)); dp["is_duplicate"] = 1
            if dp["ts"] < horizon:
                pay.append(dp)
    df = pd.DataFrame(pay).sort_values("ts", kind="stable").reset_index(drop=True)
    df.insert(0, "payment_id", [f"PAY-{i:06d}" for i in range(len(df))])
    lineage = df[["payment_id", "true_invoice_id"]].copy()
    return inv, df.drop(columns="true_invoice_id"), lineage
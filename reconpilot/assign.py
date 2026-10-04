"""Global one-to-one assignment (Hungarian) with an 'unmatched' option priced at the review threshold."""
import numpy as np
from scipy.optimize import linear_sum_assignment


def assign(pairs, review_thr):
    """pairs needs: payment_id, invoice_id, score, merchant_id. Returns {payment_id: invoice_id}."""
    out = {}
    for _, g in pairs.groupby("merchant_id"):
        pids, iids = g.payment_id.unique(), g.invoice_id.unique()
        pi = {p: k for k, p in enumerate(pids)}; ii = {i: k for k, i in enumerate(iids)}
        G = np.full((len(pids), len(iids) + len(pids)), -1e6)
        for p, i, s in zip(g.payment_id, g.invoice_id, g.score):
            G[pi[p], ii[i]] = s
        for k in range(len(pids)):
            G[k, len(iids) + k] = review_thr
        r, c = linear_sum_assignment(-G)
        for a, b in zip(r, c):
            if b < len(iids):
                out[pids[a]] = iids[b]
    return out
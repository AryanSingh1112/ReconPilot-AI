import numpy as np


def exact_score(df):
    """Exact baseline: invoice digits equal AND amount equal."""
    return ((df.ref_digits_equal == 1) & (df.amount_exact == 1)).astype(float).to_numpy()


def fuzzy_score(df):
    """Fuzzy heuristic baseline. Weights are hand-set, not tuned."""
    ref = np.maximum(df.ref_sim.fillna(0), df.narr_sim.fillna(0))
    amt = 1 - np.minimum(df.amount_diff_rel * 50, 1)
    name = df.name_sim.fillna(0.5)
    date = ((df.days_invoice_to_payment >= 0) & (df.days_invoice_to_payment <= 45)).astype(float)
    return (0.45 * ref + 0.25 * amt + 0.15 * name + 0.15 * date).to_numpy()
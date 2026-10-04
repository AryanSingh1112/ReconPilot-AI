"""Deterministic template explanation. Uses only computed values; cannot change the decision."""
import numpy as np
from . import config as C

LABELS = {
    "amount_diff_abs": "Amount difference (₹)", "amount_diff_rel": "Relative amount difference",
    "amount_exact": "Exact amount match", "ref_present": "Reference present",
    "ref_exact_full": "Full invoice id found in reference", "ref_digits_equal": "Reference digits equal invoice digits",
    "ref_prefix_frac": "Share of invoice digits given", "ref_sim": "Reference similarity",
    "ref_edit_dist": "Reference edit distance", "narr_sim": "Bank narration similarity",
    "name_sim": "Payer name similarity", "customer_known": "Customer id supplied",
    "customer_match": "Customer id matches", "days_invoice_to_payment": "Days from invoice to payment",
    "days_past_due": "Days past due date", "method_code": "Payment method", "amount_log": "Payment size",
    "hour_of_day": "Hour of day", "n_candidates": "Number of candidate invoices",
    "n_cand_same_amount": "Candidates with the same amount", "amount_rank": "Amount-closeness rank",
    "ref_sim_rank": "Reference-similarity rank", "ref_sim_gap": "Reference gap to best candidate",
    "same_amount_payments_7d": "Same-amount payments in prior 7 days",
}


def build_evidence(contrib, row, k=5):
    pairs = sorted(zip(C.FEATURES, contrib[:-1]), key=lambda x: -abs(x[1]))[:k]
    out = []
    for i, (f, c) in enumerate(pairs):
        v = row[f]
        out.append({"id": f"ev_{i + 1:02d}", "feature": f, "label": LABELS[f],
                    "value": None if v != v else round(float(v), 3),
                    "effect": "supports_match" if c > 0 else "lowers_match", "contribution": round(float(c), 4)})
    return out


def inr(v): return f"₹{v:,.2f}"


def explain(action, rule, proof, p, margin, inv_id, dq_ok, flags, model_mode):
    parts = [f"Decision {action}: {rule.replace('_', ' ').lower()}."]
    if inv_id:
        parts.append(f"Best candidate {inv_id} with match probability {p:.3f} and margin {margin:.3f} over the next candidate.")
    parts.append(f"Gross {inr(proof['gross'])} - fee {inr(proof['fee'])} - tax {inr(proof['tax'])} - refund "
                 f"{inr(proof['refund'])} = expected net {inr(proof['expected_net'])}; observed net "
                 f"{inr(proof['observed_net'])}; difference {inr(proof['difference'])} "
                 f"(tolerance {inr(proof['tolerance'])}): {'PASS' if proof['pass'] else 'FAIL'}.")
    unc = []
    if not dq_ok: unc.append("No usable reference was supplied; the match rests on amount, date and payer only.")
    if inv_id and margin < 0.2: unc.append("Another invoice scores close to the best candidate.")
    if flags.get("dup"): unc.append("An identical payment was received in the previous day.")
    if flags.get("fee_unusual"): unc.append("Fee rate differs from this merchant's contract rate.")
    if flags.get("delay_unusual"): unc.append("Settlement delay is longer than this merchant's usual window.")
    if model_mode == "simulated_outage":
        unc.append("Simulated model outage is enabled; only exact deterministic rules were applied.")
    elif model_mode == "model_unavailable":
        unc.append("The match model is unavailable; only exact deterministic rules were applied.")
    return {"provider": "template", "summary": " ".join(parts), "uncertainties": unc}
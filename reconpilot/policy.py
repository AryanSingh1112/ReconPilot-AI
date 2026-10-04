RULE_TEXT = {
    "AUTO_MATCH": "Probability, margin, amount cap and all financial checks passed.",
    "DUPLICATE_PAYMENT": "An identical payment was already received within the previous day.",
    "FINANCIAL_CHECK_FAIL": "A financial invariant failed, so this can never be auto-posted.",
    "NO_CANDIDATE_MATCH": "No invoice was confident enough to assign: the amount or reference is too far off, or the best invoice was already allocated to another payment. A person must investigate.",
    "SOLVER_UNAVAILABLE_REVIEW": "The assignment solver failed; no unsafe greedy posting is done.",
    "NO_CONFIDENT_MATCH": "Best candidate is below the review threshold.",
    "DATA_QUALITY_LOW": "No usable reference, so ML confidence alone cannot post this.",
    "PARTIAL_PAYMENT_REVIEW": "Payment is below the invoice amount; a person must confirm the partial payment.",
    "ANOMALY_REVIEW": "Fee rate or settlement delay is unusual for this merchant.",
    "BELOW_AUTO_THRESHOLD": "Probability is between the review and auto-match thresholds.",
    "MODEL_UNAVAILABLE_REVIEW": "Match model is off; only exact deterministic matches may proceed.",
    "LOW_MARGIN_REVIEW": "The best candidate leads the next one by less than the policy minimum.",
    "HIGH_VALUE_REVIEW": "Amount is above the auto-post cap for this profile.",
}
ACTION_TEXT = {"AUTO_MATCH": "Matched and passed all financial checks.",
               "REVIEW": "A person must confirm this match before it is posted.",
               "EXCEPTION": "Cannot be matched safely. Investigate."}


def decide(p, margin, inv_ok, dup, dq_ok, anomaly, amount, th, has_match=True, force_review=False, partial=False):
    if dup: return "EXCEPTION", "DUPLICATE_PAYMENT"
    if not inv_ok: return "EXCEPTION", "FINANCIAL_CHECK_FAIL"
    if not has_match: return "EXCEPTION", "NO_CANDIDATE_MATCH"
    if force_review: return "REVIEW", "SOLVER_UNAVAILABLE_REVIEW"
    if p < th["review"]: return "EXCEPTION", "NO_CONFIDENT_MATCH"
    if not dq_ok: return "REVIEW", "DATA_QUALITY_LOW"
    if partial: return "REVIEW", "PARTIAL_PAYMENT_REVIEW"
    if anomaly: return "REVIEW", "ANOMALY_REVIEW"
    if p < th["auto"]:
        return "REVIEW", ("MODEL_UNAVAILABLE_REVIEW" if th.get("outage") else "BELOW_AUTO_THRESHOLD")
    if margin < th["min_margin"]: return "REVIEW", "LOW_MARGIN_REVIEW"
    if amount > th["cap"]: return "REVIEW", "HIGH_VALUE_REVIEW"
    return "AUTO_MATCH", "AUTO_MATCH"
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, ART, MODELS = ROOT / "data", ROOT / "artifacts", ROOT / "models"
CHARTS = ART / "charts"
SEED = 42
SIM_START = datetime(2026, 1, 5)
N_DAYS = 84
DAY = 86400
TRAIN_END, VALA_END, VALB_END = 49, 56, 63      # payment-day boundaries; test = day >= 63
TAX_RATE = 0.18
NET_TOL = 100                                   # paise
MAX_SAFE_PAISE = 2**53 - 1
MAX_SAFE_AMOUNT_INR = MAX_SAFE_PAISE / 100
CAND_LIMIT = 20
CAND_MAX_AGE_DAYS = 75
REVIEW_THR = 0.20                               # policy assumption

MERCHANTS = {
    "M1": {"name": "Aurora Electronics", "fee_pct": 0.020, "lag": 2, "rate": 28, "customers": 120},
    "M2": {"name": "Banyan Apparel",     "fee_pct": 0.018, "lag": 1, "rate": 32, "customers": 150},
    "M3": {"name": "Cobalt SaaS",        "fee_pct": 0.025, "lag": 2, "rate": 20, "customers": 90},
    "M4": {"name": "Delta Travels",      "fee_pct": 0.022, "lag": 3, "rate": 24, "customers": 110},
    "M5": {"name": "Ember Foods",        "fee_pct": 0.017, "lag": 1, "rate": 36, "customers": 160},
}
# policy profiles (assumptions): max tolerated wrong-link rate among auto-matches, min margin, auto-post cap (paise)
PROFILES = {
    "fast_close":    {"max_bad": 0.02,  "min_margin": 0.10, "cap": 10_000_000},
    "balanced":      {"max_bad": 0.01,  "min_margin": 0.20, "cap": 5_000_000},
    "control_first": {"max_bad": 0.005, "min_margin": 0.35, "cap": 2_000_000},
}
OUTAGE_TH = {"review": 0.0, "auto": 0.5, "min_margin": 0.5, "outage": True}

FEATURES = [
    "amount_diff_abs", "amount_diff_rel", "amount_exact", "ref_present", "ref_exact_full",
    "ref_digits_equal", "ref_prefix_frac", "ref_sim", "ref_edit_dist", "narr_sim", "name_sim",
    "customer_known", "customer_match", "days_invoice_to_payment", "days_past_due", "method_code",
    "amount_log", "hour_of_day", "n_candidates", "n_cand_same_amount", "amount_rank",
    "ref_sim_rank", "ref_sim_gap", "same_amount_payments_7d",
]
GROUPS = {
    "reference": ["ref_present", "ref_exact_full", "ref_digits_equal", "ref_prefix_frac", "ref_sim",
                  "ref_edit_dist", "narr_sim", "ref_sim_rank", "ref_sim_gap"],
    "amount": ["amount_diff_abs", "amount_diff_rel", "amount_exact", "amount_rank", "amount_log"],
    "timing": ["days_invoice_to_payment", "days_past_due", "hour_of_day"],
    "payer": ["name_sim", "customer_known", "customer_match"],
    "context": ["n_candidates", "n_cand_same_amount", "same_amount_payments_7d", "method_code"],
}
BANNED = {"true_invoice_id", "is_duplicate", "fee_anomaly", "short_settle", "delay_anomaly",
          "ref_style", "refund_after_settlement"}
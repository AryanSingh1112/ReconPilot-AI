import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, strategies as st
from reconpilot import config as C
from reconpilot.assign import assign
from reconpilot.controls import settlement_checks
from reconpilot.features import History, pair_features
from reconpilot.pipeline import decide_all
from reconpilot.policy import decide
from reconpilot.service import build_payment_row, reconcile_batch, to_paise
from reconpilot.simulator import generate
from types import SimpleNamespace

TH = {"review": 0.2, "auto": 0.8, "min_margin": 0.2, "cap": 5_000_000}


def test_generator_deterministic():
    a, b = generate(1, days=14), generate(1, days=14)
    assert all(x.equals(y) for x, y in zip(a, b))


def test_no_banned_columns_in_features():
    assert not (set(C.FEATURES) & C.BANNED)


def test_future_records_do_not_change_features():
    inv, pay, _ = generate(2, days=20)
    k = len(pay) // 2
    t = int(pay.ts.iloc[k])
    base = pair_features(pay.iloc[[k]], inv, History(pay)).sort_values("invoice_id")
    inv2, pay2 = inv.copy(), pay.copy()
    inv2.loc[inv2.issue_ts > t, "amount"] *= 7
    fut = pay2.ts > t
    pay2.loc[fut, "amount"] = pay2.loc[fut, "amount"] * 3
    mod = pair_features(pay2.iloc[[k]], inv2, History(pay2)).sort_values("invoice_id")
    np.testing.assert_allclose(base[C.FEATURES].to_numpy(float), mod[C.FEATURES].to_numpy(float), equal_nan=True)


def test_duplicate_history_detects_same_timestamp_but_excludes_current_payment():
    pay = pd.DataFrame([
        {"payment_id": "p1", "merchant_id": "M1", "customer_id": "c1", "payer_name": "A",
         "amount": 10000, "reference": "INV-1", "ts": 100},
        {"payment_id": "p2", "merchant_id": "M1", "customer_id": "c1", "payer_name": "A",
         "amount": 10000, "reference": "INV-1", "ts": 100},
    ])
    hist = History(pay)

    assert hist.is_dup("M1", "c1", "A", 10000, "INV-1", 100, "p1")
    assert hist.is_dup("M1", "c1", "A", 10000, "INV-1", 100, "p2")
    assert not History(pay.iloc[:1]).is_dup("M1", "c1", "A", 10000, "INV-1", 100, "p1")


@given(g=st.integers(1000, 10**7), f=st.integers(0, 5000), t=st.integers(0, 900), r=st.integers(0, 500))
def test_valid_settlement_passes(g, f, t, r):
    assume(f + t + r <= g)
    p, _, ok = settlement_checks(g, f, t, r, g - f - t - r)
    assert ok and p["pass"]


def test_perturbed_settlement_fails():
    assert not settlement_checks(100000, 2000, 360, 0, 100000 - 2000 - 360 - 500)[2]


def test_refund_cannot_exceed_payment():
    assert not settlement_checks(1000, 10, 2, 2000, 1000 - 10 - 2 - 2000)[2]


def test_deductions_cannot_exceed_gross_even_when_net_equation_balances():
    proof, checks, ok = settlement_checks(100, 1000, 0, 100, -1000, 100)
    assert not ok
    assert proof["net_pass"]
    assert not proof["pass"]
    assert not next(check for check in checks if check["id"] == "INV-7")["pass"]


def test_negative_observed_net_fails_financial_checks():
    assert not settlement_checks(1000, 100, 18, 0, -1, 1000)[2]


def test_monetary_inputs_must_fit_exact_paise_range():
    assert to_paise(1.25) == 125
    with pytest.raises(ValueError, match="finite"):
        to_paise(float("inf"))
    with pytest.raises(ValueError, match="supported paise range"):
        to_paise(C.MAX_SAFE_AMOUNT_INR * 2)


def test_offset_timestamp_is_rejected_with_validation_error():
    with pytest.raises(ValueError, match="timezone-naive"):
        build_payment_row({
            "merchant_id": "M1",
            "amount": 100,
            "payment_time": "2026-10-01T10:00:00+05:30",
        })


def test_policy_rules():
    assert decide(0.95, 0.5, True, False, True, False, 1000, TH)[0] == "AUTO_MATCH"
    assert decide(0.95, 0.5, False, False, True, False, 1000, TH)[0] == "EXCEPTION"
    assert decide(0.95, 0.5, True, True, True, False, 1000, TH)[0] == "EXCEPTION"
    assert decide(0.95, 0.5, True, False, False, False, 1000, TH)[0] == "REVIEW"
    assert decide(0.95, 0.05, True, False, True, False, 1000, TH)[1] == "LOW_MARGIN_REVIEW"
    assert decide(0.95, 0.5, True, False, True, False, 9_000_000, TH)[1] == "HIGH_VALUE_REVIEW"
    assert decide(0.1, 0.1, True, False, True, False, 1000, TH)[0] == "EXCEPTION"


def test_assignment_never_double_allocates():
    pairs = pd.DataFrame({"payment_id": ["a", "b", "b"], "invoice_id": ["i1", "i1", "i2"],
                          "score": [0.9, 0.95, 0.5], "merchant_id": "M1"})
    out = assign(pairs, 0.2)
    assert len(set(out.values())) == len(out)


def test_batch_decision_uses_global_assignment():
    pay = pd.DataFrame([
        {"payment_id": "p1", "merchant_id": "M1", "customer_id": "c1", "payer_name": "A", "amount": 10000,
         "ts": 10, "method": "upi", "reference": "INV-00001", "narration": "UPI/INV-00001/A", "fee": 200,
         "fee_tax": 36, "refund": 0, "observed_net": 9764, "settle_ts": 2 * C.DAY, "is_duplicate": 0,
         "fee_anomaly": 0, "short_settle": 0, "delay_anomaly": 0},
        {"payment_id": "p2", "merchant_id": "M1", "customer_id": "c2", "payer_name": "B", "amount": 10000,
         "ts": 20, "method": "upi", "reference": "INV-00001", "narration": "UPI/INV-00001/B", "fee": 200,
         "fee_tax": 36, "refund": 0, "observed_net": 9764, "settle_ts": 2 * C.DAY, "is_duplicate": 0,
         "fee_anomaly": 0, "short_settle": 0, "delay_anomaly": 0}
    ])
    inv = pd.DataFrame([
        {"invoice_id": "INV-00001", "merchant_id": "M1", "customer_id": "c1", "customer_name": "A", "amount": 10000,
         "issue_ts": 0, "due_ts": 30 * C.DAY},
        {"invoice_id": "INV-00002", "merchant_id": "M1", "customer_id": "c2", "customer_name": "B", "amount": 10000,
         "issue_ts": 0, "due_ts": 30 * C.DAY}
    ])
    hist = History(pay)
    pairs = pd.DataFrame([
        {"payment_id": "p1", "invoice_id": "INV-00001", "score": 0.99, "merchant_id": "M1"},
        {"payment_id": "p1", "invoice_id": "INV-00002", "score": 0.60, "merchant_id": "M1"},
        {"payment_id": "p2", "invoice_id": "INV-00001", "score": 0.98, "merchant_id": "M1"},
        {"payment_id": "p2", "invoice_id": "INV-00002", "score": 0.65, "merchant_id": "M1"},
    ])
    out = decide_all(pay, pairs, {"review": 0.2, "auto": 0.8, "min_margin": 0.2, "cap": 5_000_000}, hist,
                     {"INV-00001": 10000, "INV-00002": 10000}, use_assignment=True)
    assert out["assigned"].nunique() == 2
    assert set(out["assigned"].dropna()) <= {"INV-00001", "INV-00002"}


def test_service_batch_uses_global_assignment_for_competing_payments():
    invoices = pd.DataFrame([
        {"invoice_id": "INV-00001", "merchant_id": "M1", "customer_id": "c1", "customer_name": "A",
         "amount": 10000, "issue_ts": 0, "due_ts": 30 * C.DAY},
        {"invoice_id": "INV-00002", "merchant_id": "M1", "customer_id": "c2", "customer_name": "B",
         "amount": 10000, "issue_ts": 0, "due_ts": 30 * C.DAY},
    ])
    empty_payments = pd.DataFrame(columns=[
        "payment_id", "merchant_id", "customer_id", "payer_name", "amount", "ts", "method", "reference",
        "narration", "fee", "fee_tax", "refund", "observed_net", "settle_ts",
    ])
    state = SimpleNamespace(
        inv=invoices,
        pay=empty_payments,
        hist=History(empty_payments),
        inv_amount=dict(zip(invoices.invoice_id, invoices.amount)),
        inv_by_id=invoices.set_index("invoice_id"),
        bundle=None,
    )
    common = {
        "merchant_id": "M1", "amount": 100, "method": "upi", "reference": "INV-00001",
        "fee": 2, "fee_tax": 0.36, "refund": 0, "observed_net": 97.64,
        "profile": "balanced", "model_off": True,
    }
    requests = [
        {**common, "payment_id": "batch-p1", "customer_id": "c1", "payer_name": "A"},
        {**common, "payment_id": "batch-p2", "customer_id": "c2", "payer_name": "B"},
    ]

    results = reconcile_batch(state, requests)
    assigned = [result["assigned_invoice"] for result in results if result["assigned_invoice"]]
    assert "INV-00001" in assigned
    assert len(assigned) == len(set(assigned))


def test_service_batch_rejects_duplicate_payment_ids():
    with pytest.raises(ValueError, match="unique"):
        reconcile_batch(SimpleNamespace(), [
            {"payment_id": "same", "profile": "balanced"},
            {"payment_id": "same", "profile": "balanced"},
        ])


def test_partial_payment_goes_to_review():
    assert decide(0.99, 0.9, True, False, True, False, 1000, TH, True, False, True)[1] == "PARTIAL_PAYMENT_REVIEW"
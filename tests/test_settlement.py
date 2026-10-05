import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st
from reconpilot import config as C, settlement as ST
from reconpilot.simulator import generate

BID = "SB-M1-D005"


def mk(nets, day=5, prefix="P", observed=None, merchant="M1"):
    n = len(nets)
    return pd.DataFrame({"payment_id": [f"{prefix}{i}" for i in range(n)], "merchant_id": merchant,
                         "amount": nets, "fee": 0, "fee_tax": 0, "refund": 0,
                         "observed_net": observed if observed is not None else nets,
                         "settle_ts": day * C.DAY + 3600, "short_settle": 0})


def run(nets, credit_delta=0, profile="balanced", observed=None):
    L = ST.Ledger(mk(nets, observed=observed), inject=False)
    statement = sum(observed if observed is not None else nets)
    return ST.reconcile_credit(L, BID, statement + credit_delta, profile)


def test_clean_credit_auto_matches():
    r = run([100001, 200003, 300007])
    assert (r["action"], r["rule"]) == ("AUTO_MATCH", "CREDIT_RECONCILED")


def test_tolerance_boundary():
    assert run([100001, 200003], credit_delta=100)["action"] == "AUTO_MATCH"
    assert run([100001, 200003], credit_delta=101)["action"] != "AUTO_MATCH"
    assert run([100001, 200003], credit_delta=-100)["action"] == "AUTO_MATCH"


def test_missing_payment_is_identified():
    r = run([100001, 233333, 345679], credit_delta=-233333)
    assert r["rule"] == "MISSING_PAYMENT_LIKELY" and r["explanation"]["payment_ids"] == ["P1"]
    assert r["action"] == "REVIEW"


def test_ambiguous_when_two_payments_fit():
    r = run([100000, 100000, 333333], credit_delta=-100000)
    assert r["rule"] == "AMBIGUOUS_EXPLANATION" and r["explanation"]["n_solutions"] == 2


def test_round_adjustment():
    r = run([123457, 234569, 345671, 456783], credit_delta=-50000)
    assert r["rule"] == "ROUND_ADJUSTMENT_LIKELY"


def test_large_unexplained_is_exception():
    r = run([100000, 230000, 350000, 470000], credit_delta=-333333)
    assert (r["action"], r["rule"]) == ("EXCEPTION", "LARGE_UNEXPLAINED_VARIANCE")


def test_small_unexplained_goes_to_review():
    r = run([100000, 230000, 350000, 470000], credit_delta=-300)
    assert (r["action"], r["rule"]) == ("REVIEW", "SMALL_UNEXPLAINED_VARIANCE")


def test_no_credit_is_exception():
    L = ST.Ledger(mk([100001]), inject=False)
    assert ST.reconcile_credit(L, BID, 0)["rule"] == "NO_CREDIT_RECEIVED"


def test_short_versus_contract_never_auto():
    r = run([100001, 200003], observed=[100001 - 500, 200003])
    assert (r["action"], r["rule"]) == ("REVIEW", "SHORT_VS_CONTRACT_REVIEW")
    assert r["short_payments"][0]["payment_id"] == "P0"


def test_high_value_batch_depends_on_profile():
    assert run([25_000_000], profile="fast_close")["action"] == "AUTO_MATCH"
    assert run([25_000_000], profile="control_first")["rule"] == "HIGH_VALUE_BATCH_REVIEW"


def test_cross_batch_payment_is_identified():
    pay = pd.concat([mk([123456, 234567, 345678], day=5, prefix="A"), mk([111111, 222222], day=6, prefix="B")],
                    ignore_index=True)
    L = ST.Ledger(pay, inject=False)
    r = ST.reconcile_credit(L, "SB-M1-D006", 111111 + 222222 + 234567)
    assert r["rule"] == "CROSS_BATCH_PAYMENT_LIKELY" and r["explanation"]["payment_ids"] == ["A1"]


@settings(max_examples=60, deadline=None)
@given(nets=st.lists(st.integers(1000, 10**6), min_size=1, max_size=8),
       delta=st.integers(101, 10**6), sign=st.sampled_from([-1, 1]))
def test_variance_beyond_tolerance_is_never_auto(nets, delta, sign):
    assert run(nets, credit_delta=sign * delta)["action"] != "AUTO_MATCH"


def test_ledger_is_deterministic_and_injection_is_consistent():
    _, pay, _ = generate(3, days=40)
    a, b = ST.Ledger(pay), ST.Ledger(pay)
    assert [r["credit"] for r in a.rows] == [r["credit"] for r in b.rows]
    for r in a.rows:
        g = a.members[r["batch_id"]]
        if r["has_short"]:
            assert r["truth"] == "statement_short" and r["credit"] == r["statement_total"]
        if r["truth"] == "missing_payment":
            net = int(g[g.payment_id == r["truth_detail"]].observed_net.iloc[0])
            assert r["credit"] == r["statement_total"] - net
import pytest
from fastapi.testclient import TestClient
from reconpilot import config as C
from backend.main import app

pytestmark = pytest.mark.skipif(not (C.MODELS / "bundle.joblib").exists(), reason="train first")

def test_settlement_demo_replays_and_missing_payment_is_never_auto():
    with TestClient(app) as c:
        sc = {s["id"] for s in c.get("/v1/settlements/scenarios").json()}
        assert "clean" in sc
        r = c.post("/v1/settlements/demo", json={"scenario_id": "missing_payment", "seed": 0}).json()
        assert r["action"] != "AUTO_MATCH"
        rid = c.get("/v1/audit").json()[0]["id"]
        assert c.post(f"/v1/replay/{rid}").json()["reproduced"] is True
        assert c.get("/v1/audit/verify").json()["valid"] is True


def test_api_allows_local_frontend_origin():
    with TestClient(app) as c:
        response = c.options(
            "/v1/demo/scenarios",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_demo_replay_and_chain():
    with TestClient(app) as c:
        r = c.post("/v1/demo/run", json={"scenario_id": "clean_exact", "seed": 0}).json()
        assert r["action"] in {"AUTO_MATCH", "REVIEW", "EXCEPTION"}
        rid = c.get("/v1/audit").json()[0]["id"]
        assert c.post(f"/v1/replay/{rid}").json()["reproduced"] is True
        assert c.get("/v1/audit/verify").json()["valid"] is True


def test_model_off_never_uses_model():
    with TestClient(app) as c:
        r = c.post("/v1/demo/run", json={"scenario_id": "ambiguous", "seed": 0, "model_off": True}).json()
        assert r["mode"] == "simulated_outage"
        assert r["model"] == "exact_rules_only"
        assert r["evidence"] == []


def test_pan_rejected():
    with TestClient(app) as c:
        resp = c.post("/v1/reconcile/case", json={"merchant_id": "M1", "amount": 100, "reference": "4111111111111111"})
        assert resp.status_code == 422


def test_formatted_pan_rejected():
    with TestClient(app) as c:
        resp = c.post("/v1/reconcile/case", json={
            "merchant_id": "M1", "amount": 100, "narration": "Card 4111-1111-1111-1111"
        })
        assert resp.status_code == 422


def test_offset_timestamp_returns_validation_error():
    with TestClient(app) as c:
        resp = c.post("/v1/reconcile/case", json={
            "merchant_id": "M1", "amount": 100, "payment_time": "2026-10-01T10:00:00+05:30"
        })
        assert resp.status_code == 422
        assert "timezone-naive" in resp.json()["detail"]


def test_negative_observed_net_is_rejected():
    with TestClient(app) as c:
        resp = c.post("/v1/reconcile/case", json={
            "merchant_id": "M1", "amount": 100, "observed_net": -0.01
        })
        assert resp.status_code == 422


def test_batch_route_assigns_competing_invoice_at_most_once():
    with TestClient(app) as c:
        invoices = c.get("/v1/invoices", params={"merchant_id": "M1", "limit": 10000}).json()
        invoice = invoices[-1]
        common = {
            "merchant_id": "M1", "amount": invoice["amount"], "reference": invoice["invoice_id"],
            "customer_id": invoice["customer_id"], "payer_name": invoice["customer_name"].upper(),
        }
        resp = c.post("/v1/reconcile/batch", json={"cases": [
            {**common, "payment_id": "api-batch-1"},
            {**common, "payment_id": "api-batch-2"},
        ]})
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assigned = [row["assigned_invoice"] for row in result["results"] if row["assigned_invoice"]]
        assert result["count"] == 2
        assert len(assigned) == len(set(assigned))
        assert result["summary"]["payments_per_second"] > 0
        assert all(row["audit_persisted"] for row in result["results"])


def test_invariant_failure_never_auto_matches():
    with TestClient(app) as c:
        r = c.post("/v1/demo/run", json={"scenario_id": "short_settle", "seed": 0}).json()
        assert r["action"] != "AUTO_MATCH"


def test_duplicate_is_exception():
    with TestClient(app) as c:
        r = c.post("/v1/demo/run", json={"scenario_id": "duplicate", "seed": 0}).json()
        assert r["action"] == "EXCEPTION"


def test_manual_payment_is_added_to_session_history_and_repeat_is_detected():
    request = {
        "merchant_id": "M1",
        "amount": 4321.09,
        "reference": "MANUAL-DUPLICATE-SESSION-TEST",
        "customer_id": "manual-duplicate-session-test",
        "payer_name": "SESSION TEST",
    }

    with TestClient(app) as c:
        first = c.post("/v1/reconcile/case", json=request)
        assert first.status_code == 200, first.text
        first_result = first.json()
        assert first_result["payment_id"].startswith("MANUAL-")

        repeated = c.post("/v1/reconcile/case", json=request)
        assert repeated.status_code == 200, repeated.text
        repeated_result = repeated.json()
        assert repeated_result["payment_id"] != first_result["payment_id"]
        assert repeated_result["action"] == "EXCEPTION"
        assert repeated_result["rule"] == "DUPLICATE_PAYMENT"


def test_manual_payment_id_cannot_be_reused():
    with TestClient(app) as c:
        payload = {
            "merchant_id": "M1",
            "amount": 4321.10,
            "payment_id": "manual-id-reuse-test",
            "reference": "MANUAL-ID-REUSE-TEST",
        }
        first = c.post("/v1/reconcile/case", json=payload)
        assert first.status_code == 200, first.text

        repeated = c.post("/v1/reconcile/case", json=payload)
        assert repeated.status_code == 409
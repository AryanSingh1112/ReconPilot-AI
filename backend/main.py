import hashlib, json, os, re, time
from contextlib import asynccontextmanager
from uuid import uuid4
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from reconpilot import config as C
from reconpilot import settlement as ST
from reconpilot.features import History
from reconpilot.service import (build_payment_row, default_payment_time, load_state, reconcile_batch,
                                reconcile_case, scenario_request)

S = None
_LEDGER = {}
C.CHARTS.mkdir(parents=True, exist_ok=True)
C.ART.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{C.ART / 'audit.db'}")


@asynccontextmanager
async def lifespan(app):
    global S
    with engine.begin() as cx:
        cx.execute(text("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, payload TEXT, prev_hash TEXT, hash TEXT)"))
        cx.execute(text("CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END"))
        cx.execute(text("CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END"))
    try:
        S = load_state()
    except Exception as e:
        print("State not loaded. Run: python -m scripts.run_experiments --regen", e)
    yield


app = FastAPI(title="ReconPilot", lifespan=lifespan)

allowed_origins = [
    "https://reconpilot-ai-1.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CaseRequest(BaseModel):
    model_config = {"extra": "forbid"}

    merchant_id: str
    amount: float = Field(gt=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    method: str = "upi"
    reference: str = Field(default="", max_length=512)
    narration: str = Field(default="", max_length=1024)
    customer_id: str = Field(default="", max_length=128)
    payer_name: str = Field(default="", max_length=256)
    payment_time: str | None = Field(default=None, max_length=64)
    fee: float | None = Field(default=None, ge=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    fee_tax: float | None = Field(default=None, ge=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    refund: float | None = Field(default=0, ge=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    observed_net: float | None = Field(default=None, ge=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    settlement_lag_days: float | None = Field(default=None, ge=0, le=36500, allow_inf_nan=False)
    profile: str = "balanced"
    model_off: bool = False
    payment_id: str | None = Field(default=None, max_length=128)


class DemoRequest(BaseModel):
    scenario_id: str
    seed: int = 0
    profile: str = "balanced"
    model_off: bool = False


class BatchCaseRequest(BaseModel):
    cases: list[CaseRequest] = Field(min_length=1, max_length=500)


class InvoiceIn(BaseModel):
    merchant_id: str
    customer_name: str = Field(min_length=1, max_length=256)
    amount: float = Field(gt=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    customer_id: str = Field(default="", max_length=128)


class SettleDemo(BaseModel):
    scenario_id: str = Field(
        description="Choose an ID returned by GET /v1/settlements/scenarios.",
        json_schema_extra={"enum": list(ST.SCENARIOS)},
    )
    seed: int = 0
    profile: str = "balanced"


class SettleCredit(BaseModel):
    batch_id: str = Field(max_length=64)
    credit: float = Field(ge=0, le=C.MAX_SAFE_AMOUNT_INR, allow_inf_nan=False)
    profile: str = "balanced"


def need_state():
    if S is None:
        raise HTTPException(503, "Run: python -m scripts.run_experiments --regen")


def validate_new_payment_ids(reqs):
    existing = set(S.pay["payment_id"])
    duplicates = {req["payment_id"] for req in reqs if req["payment_id"] in existing}
    if duplicates:
        raise HTTPException(409, "payment_id already exists in the current payment history")


def remember_payments(reqs):
    rows = pd.concat([build_payment_row(req) for req in reqs], ignore_index=True)
    S.pay = pd.concat([S.pay, rows], ignore_index=True)
    S.hist = History(S.pay)


def audit_write_many(payloads):
    with engine.begin() as cx:
        prev = cx.execute(text("SELECT hash FROM audit ORDER BY id DESC LIMIT 1")).scalar() or "GENESIS"
        for payload in payloads:
            body = json.dumps(payload, sort_keys=True, default=str)
            h = hashlib.sha256((prev + body).encode()).hexdigest()
            cx.execute(text("INSERT INTO audit(ts,payload,prev_hash,hash) VALUES(:t,:p,:ph,:h)"),
                       {"t": time.time(), "p": body, "ph": prev, "h": h})
            prev = h


def validate_case(req):
    if req["merchant_id"] not in C.MERCHANTS:
        raise HTTPException(422, "unknown merchant_id")
    if req.get("profile", "balanced") not in C.PROFILES:
        raise HTTPException(422, "unknown profile")
    if req.get("method", "upi") not in ("card", "upi", "netbanking", "wallet"):
        raise HTTPException(422, "unknown method")
    for field in ("reference", "narration", "customer_id", "payer_name"):
        value = req.get(field) or ""
        if re.search(r"(?:\d[ \t-]*){13,19}", value):
            raise HTTPException(422, "Card-number-like value rejected. Do not send PAN data.")


def run_case(req, source):
    need_state()
    if source == "manual":
        req = dict(req)
        req["payment_id"] = req.get("payment_id") or f"MANUAL-{uuid4().hex}"
        validate_new_payment_ids([req])
    validate_case(req)
    try:
        res = reconcile_case(S, req)
    except ValueError as e:
        raise HTTPException(422, str(e))
    summ = {k: res[k] for k in ("action", "rule", "probability", "margin", "assigned_invoice", "mode", "payment_id")}
    try:
        audit_write_many([{"source": source, "request": req, "summary": summ}])
    except SQLAlchemyError as e:
        raise HTTPException(503, "Decision could not be persisted to the audit log") from e
    if source == "manual":
        remember_payments([req])
    res["audit_persisted"] = True
    return res


def read_json(name):
    p = C.ART / "eval_json" / name
    return json.loads(p.read_text()) if p.exists() else None


def ledger():
    need_state()
    if "L" not in _LEDGER:
        _LEDGER["L"] = ST.Ledger(pd.read_parquet(C.DATA / "payments.parquet"))
    return _LEDGER["L"]


def run_credit(batch_id, credit_paise, profile, source, scenario=None):
    L = ledger()
    if batch_id not in L.members:
        raise HTTPException(404, "unknown batch_id")
    if profile not in ST.BATCH_CAP:
        raise HTTPException(422, "unknown profile")
    res = ST.reconcile_credit(L, batch_id, credit_paise, profile)
    summ = {"action": res["action"], "rule": res["rule"], "probability": None, "margin": None,
            "assigned_invoice": None, "mode": "settlement", "payment_id": batch_id,
            "variance_paise": res["variance_paise"]}
    try:
        audit_write_many([{"kind": "settlement", "source": source,
                           "request": {"batch_id": batch_id, "credit_paise": int(credit_paise), "profile": profile},
                           "summary": summ}])
    except SQLAlchemyError as e:
        raise HTTPException(503, "Decision could not be persisted to the audit log") from e
    res["audit_persisted"] = True
    if scenario:
        res["scenario"] = scenario
    return res


@app.get("/health")
def health():
    return {"status": "ok", "state_loaded": S is not None, "model_loaded": bool(S and S.bundle)}


@app.get("/v1/models/active")
def active():
    rep = read_json("test.json"); src = "test"
    if rep is None:
        rep, src = read_json("validation.json"), "validation"
    head = None
    if rep:
        d = rep["methods"]["lgbm"]["decision"]
        head = {"source": src, "precision": d["auto_precision"], "recall": d["straight_through_recall"],
                "incorrect_auto_post": d["incorrect_auto_post_rate"], "auto_rate": d["auto_rate"], "f1": d["f1"]}
    return {"model": S.bundle["version"] if S and S.bundle else None, "n_features": len(C.FEATURES),
            "profiles": S.bundle["thresholds"] if S and S.bundle else None, "headline": head,
            "merchants": {k: v["name"] for k, v in C.MERCHANTS.items()}, "default_payment_time": default_payment_time()}


@app.get("/v1/demo/scenarios")
def scenarios():
    need_state()
    return [{"id": k, "title": v[0], "description": v[1], "available": len(v[2])} for k, v in S.scen.items()]


@app.post("/v1/demo/run")
def demo(r: DemoRequest):
    need_state()
    if r.scenario_id not in S.scen:
        raise HTTPException(404, "unknown scenario")
    req = {**scenario_request(S, r.scenario_id, r.seed), "profile": r.profile, "model_off": r.model_off}
    res = run_case(req, "demo")
    res["scenario"] = {"id": r.scenario_id, "title": S.scen[r.scenario_id][0], "seed": r.seed}
    return res


@app.post("/v1/reconcile/case")
def case(r: CaseRequest):
    return run_case(r.model_dump(), "manual")


@app.post("/v1/reconcile/batch")
def batch(r: BatchCaseRequest):
    need_state()
    reqs = [c.model_dump() for c in r.cases]
    for req in reqs:
        if not req.get("payment_id"):
            req["payment_id"] = f"BATCH-{uuid4().hex}"
        validate_case(req)
    validate_new_payment_ids(reqs)
    started = time.perf_counter()
    try:
        out = reconcile_batch(S, reqs)
    except ValueError as e:
        raise HTTPException(422, str(e))
    payloads = []
    for req, result in zip(reqs, out):
        summary = {k: result[k] for k in
                   ("action", "rule", "probability", "margin", "assigned_invoice", "mode", "payment_id")}
        payloads.append({"source": "batch", "request": req, "summary": summary})
    try:
        audit_write_many(payloads)
    except SQLAlchemyError as e:
        raise HTTPException(503, "Batch decisions could not be persisted to the audit log") from e
    remember_payments(reqs)
    for result in out:
        result["audit_persisted"] = True
    elapsed = time.perf_counter() - started
    counts = {action: sum(result["action"] == action for result in out)
              for action in ("AUTO_MATCH", "REVIEW", "EXCEPTION")}
    return {"count": len(out), "summary": {
        "decision_counts": counts, "elapsed_seconds": elapsed,
        "payments_per_second": len(out) / elapsed if elapsed else None,
    }, "results": out}


@app.get("/v1/invoices")
def invoices(merchant_id: str, limit: int = 6):
    need_state()
    cutoff = (C.VALB_END + 3) * C.DAY
    d = S.inv[(S.inv.merchant_id == merchant_id) & (S.inv.issue_ts <= cutoff)].tail(limit)
    return [{"invoice_id": r.invoice_id, "customer_id": r.customer_id, "customer_name": r.customer_name,
             "amount": r.amount / 100} for r in d.itertuples()]


@app.post("/v1/invoices")
def add_invoice(r: InvoiceIn):
    need_state()
    if r.merchant_id not in C.MERCHANTS:
        raise HTTPException(422, "unknown merchant_id")
    n = int((S.inv.invoice_id.str.slice(4).astype(int) >= 90000).sum())
    iid = f"INV-{90000 + n + 1:05d}"
    issue_ts = (C.VALB_END + 2) * C.DAY
    row = {"invoice_id": iid, "merchant_id": r.merchant_id, "customer_id": r.customer_id or f"{r.merchant_id}-C999",
           "customer_name": r.customer_name, "amount": int(round(r.amount * 100)),
           "issue_ts": issue_ts, "due_ts": issue_ts + 30 * C.DAY}
    S.inv = pd.concat([S.inv, pd.DataFrame([row])], ignore_index=True)
    S.inv_amount[iid] = row["amount"]
    S.inv_by_id = S.inv.set_index("invoice_id")
    return {"invoice_id": iid, "amount": r.amount, "customer_name": r.customer_name}


@app.get("/v1/settlements/scenarios")
def settlement_scenarios():
    L = ledger()
    return [{"id": k, "title": v[0], "description": v[1], "available": L.count(k)}
            for k, v in ST.SCENARIOS.items() if L.count(k)]


@app.post("/v1/settlements/demo")
def settlement_demo(r: SettleDemo):
    L = ledger()
    if r.scenario_id not in ST.SCENARIOS:
        raise HTTPException(404, "unknown scenario")
    pick = L.pick(r.scenario_id, r.seed)
    if pick is None:
        raise HTTPException(404, "no batch for this scenario")
    return run_credit(pick["batch_id"], pick["credit"], r.profile, "settlement_demo",
                      {"id": r.scenario_id, "title": ST.SCENARIOS[r.scenario_id][0], "seed": r.seed})


@app.get("/v1/settlements/batches")
def settlement_batches(merchant_id: str):
    if merchant_id not in C.MERCHANTS:
        raise HTTPException(422, "unknown merchant_id")
    return ledger().batch_list(merchant_id)


@app.post("/v1/settlements/credit")
def settlement_credit(r: SettleCredit):
    return run_credit(r.batch_id, int(round(r.credit * 100)), r.profile, "settlement_manual")


@app.get("/v1/metrics/model-performance")
def perf():
    rep = read_json("test.json"); src = "test"
    if rep is None:
        rep, src = read_json("validation.json"), "validation"
    mp = C.ART / "manifest.json"
    return {"source": src, "report": rep, "dataset_card": read_json("dataset_card.json"),
            "manifest": json.loads(mp.read_text()) if mp.exists() else None}


@app.get("/v1/metrics/settlement")
def settlement_metrics():
    return {"report": read_json("settlement.json")}


@app.get("/v1/audit")
def audit(limit: int = 20):
    with engine.begin() as cx:
        rows = cx.execute(text("SELECT id,ts,payload,hash FROM audit ORDER BY id DESC LIMIT :l"), {"l": limit}).all()
    return [{"id": r[0], "ts": r[1], "payload": json.loads(r[2]), "hash": r[3]} for r in rows]


@app.get("/v1/audit/verify")
def verify():
    with engine.begin() as cx:
        rows = cx.execute(text("SELECT payload,prev_hash,hash FROM audit ORDER BY id")).all()
    prev = "GENESIS"
    for i, (payload, ph, h) in enumerate(rows):
        if ph != prev or hashlib.sha256((prev + payload).encode()).hexdigest() != h:
            return {"valid": False, "broken_at_row": i + 1}
        prev = h
    return {"valid": True, "rows": len(rows)}


@app.post("/v1/replay/{audit_id}")
def replay(audit_id: int):
    need_state()
    with engine.begin() as cx:
        row = cx.execute(text("SELECT payload FROM audit WHERE id=:i"), {"i": audit_id}).scalar()
    if row is None:
        raise HTTPException(404, "audit row not found")
    old = json.loads(row)
    if old.get("kind") == "settlement":
        rq = old["request"]
        res = ST.reconcile_credit(ledger(), rq["batch_id"], rq["credit_paise"], rq["profile"])
        new = {"action": res["action"], "rule": res["rule"], "variance_paise": res["variance_paise"]}
        diff = {k: {"stored": old["summary"].get(k), "replayed": new[k]}
                for k in new if old["summary"].get(k) != new[k]}
        return {"reproduced": not diff, "diff": diff}
    res = reconcile_case(S, old["request"])
    new = {k: res[k] for k in ("action", "rule", "probability", "margin", "assigned_invoice", "mode", "payment_id")}
    diff = {}
    for k in new:
        a, b = old["summary"][k], new[k]
        changed = abs(a - b) > 1e-9 if isinstance(b, float) and a is not None else a != b
        if changed:
            diff[k] = {"stored": a, "replayed": b}
    return {"reproduced": not diff, "diff": diff}


app.mount("/charts", StaticFiles(directory=C.CHARTS, check_dir=False), name="charts")
DIST = C.ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
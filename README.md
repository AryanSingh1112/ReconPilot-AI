# ReckonPilot

**An explainable payment-to-invoice reconciliation prototype with deterministic financial controls.**

ReckonPilot generates candidate invoices for incoming payments, scores candidate matches, assigns invoices globally so an invoice is not allocated to multiple payments in a batch, validates settlement arithmetic, and returns an auditable recommendation: `AUTO_MATCH`, `REVIEW`, or `EXCEPTION`.

> **Prototype only.** The included invoice and training data is simulated. ReckonPilot is not connected to Razorpay, a bank, or any payment processor, and it does not post or move money. It has no authentication and is not production-hardened. Do not send real customer or payment data to this application.

## Contents

- [The problem](#the-problem)
- [Key capabilities](#key-capabilities)
- [Architecture](#architecture)
- [Technology](#technology)
- [Dataset and methodology](#dataset-and-methodology)
- [Evaluation results](#evaluation-results)
- [Decision policy](#decision-policy)
- [Explainability and audit trail](#explainability-and-audit-trail)
- [API and dashboard](#api-and-dashboard)
- [Project structure](#project-structure)
- [Run locally](#run-locally)
- [Experiments and evaluation](#experiments-and-evaluation)
- [Tests](#tests)
- [Limitations and handoff notes](#limitations-and-handoff-notes)

## The problem

Payment reconciliation has two related but different questions:

1. Which invoice, if any, is the best candidate for a payment?
2. Is that match safe enough to accept automatically, given settlement checks, ambiguity, and business policy?

ReckonPilot keeps candidate scoring separate from the deterministic decision policy. A high match score alone is not sufficient for `AUTO_MATCH`: the payment must also pass financial checks, not be a duplicate or partial payment, satisfy the configured confidence and margin thresholds, and be within the profile's amount cap.

## Key capabilities

- **Candidate matching:** derives 24 payment/invoice features, including amount difference, reference and narration similarity, payer/customer signals, timing, candidate ranks, and recent same-amount payment context.
- **Several matchers for comparison:** exact rules, fuzzy matching, logistic regression, and LightGBM; model scores are calibrated before threshold-based decisioning.
- **One-to-one batch assignment:** uses the Hungarian algorithm with an unmatched option, instead of independently assigning each payment its top candidate.
- **Deterministic settlement controls:** checks gross amount, fee, tax, refund, observed net, and—when there is an invoice candidate—the payment amount against the invoice amount.
- **Guarded outcomes:** emits `AUTO_MATCH`, `REVIEW`, or `EXCEPTION` with a rule identifier and human-readable explanation.
- **Model outage mode:** supports a model-off path that uses exact deterministic matching rather than pretending the model is available.
- **Decision evidence:** returns candidate details, financial proof, flags, and feature contributions for a selected LightGBM match.
- **Append-only audit records:** records decisions in SQLite and provides a hash-chain verification endpoint and a replay endpoint.
- **Interactive dashboard:** supports demo scenarios, manual reconciliation, model evaluation, and audit review.

## Architecture

```text
Payment input + invoice and payment history
                  |
                  v
     Request validation (FastAPI / Pydantic)
                  |
                  v
     Candidate generation and 24 features
                  |
                  v
       Calibrated match probabilities
                  |
                  v
   Global one-to-one assignment (Hungarian)
                  |
                  v
 Financial invariants + duplicate/anomaly checks
                  |
                  v
    Ordered policy: AUTO_MATCH / REVIEW / EXCEPTION
           |                         |
           v                         v
  Evidence and explanation      SQLite audit log
           \                         /
            +--- JSON API response --+
                         |
                         v
                 React dashboard
```

The model estimates match likelihood; it does not execute a financial action. The policy and financial controls determine the returned outcome.

## Technology

| Area | Technology |
| --- | --- |
| Matching and evaluation | Python, pandas, NumPy, scikit-learn, LightGBM |
| Global assignment | SciPy's linear assignment solver |
| API and validation | FastAPI, Pydantic, Uvicorn |
| Audit persistence | SQLite through SQLAlchemy |
| Dashboard | React 19 and Vite |
| Tests | pytest, Hypothesis, FastAPI TestClient |

## Dataset and methodology

The included dataset is produced by the simulator in `reconpilot/simulator.py`; it is not transaction data from a bank, payment processor, or real merchant.

- Seed: `42`; configured simulation horizon: 84 days.
- Five synthetic merchants with different simulated fees and settlement lags.
- The checked-in dataset contains 10,148 payments, 12,253 invoices, and 159,144 generated payment/invoice candidate pairs.
- The candidate-pair labels and true invoice lineage are kept separate from model features.
- Evaluation is split chronologically by payment day: train, validation A, validation B, and a held-out test period. The test period starts at day 63.
- The `spaced` reference format is held out from training and appears in the test period.
- Candidate generation is capped at 20 candidates per payment; the held-out candidate recall at that limit is 98.83%.

The data generator deliberately simulates reference corruption, missing references, duplicate payments, fee anomalies, delayed settlements, refunds, and short settlements. Results demonstrate behavior on these simulator assumptions only; they do not establish performance on real payment data.

## Evaluation results

The following snapshot is from the held-out test report in the current working tree: 2,650 payments and 46,054 candidate pairs. All four matchers use the same balanced decision policy, with thresholds selected on validation data. `Pair PR-AUC` measures ranking across candidate pairs; `Top-1` is the highest-scoring invoice before policy outcomes. `Auto precision` measures correct automatic matches, while `straight-through recall` measures the share of eligible payments correctly auto-matched.

| Matcher | Pair PR-AUC | Top-1 | Auto rate | Auto precision | Straight-through recall | Incorrect auto-posts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exact rules | 0.7468 | 84.72% | 65.47% | 100.00% | 68.31% | 0 |
| Fuzzy | 0.8798 | 93.89% | 12.75% | 100.00% | 13.31% | 0 |
| Logistic regression | 0.9894 | 95.17% | 79.47% | 100.00% | 82.91% | 0 |
| LightGBM | 0.9920 | 95.55% | 79.81% | 99.95% | 83.23% | 1 |

**Important:** the LightGBM test snapshot contains one incorrect automatic match. The measured 99.95% auto precision is not a guarantee of safety, and this project must not be treated as production-ready or as evidence of real-world accuracy. The figures are simulator-specific and can change when the data or experiment is regenerated.

The final test evaluation is guarded by `artifacts/test_eval.lock`: the experiment runner refuses to evaluate the test set again after that lock exists. The evaluation JSON is generated locally and is not necessarily present in a fresh checkout; the dashboard falls back to the checked-in validation report when no test report is available.

The dashboard's Evaluation tab shows this saved offline benchmark; its metrics do not change when you submit manual or batch demo payments. Those demo decisions do not have verified ground-truth labels, so the dashboard intentionally omits the saved benchmark charts rather than presenting them as if they described the current demo session. The experiment runner still writes its plots to `artifacts/charts/`.

## Decision policy

The policy returns one of three outcomes:

| Outcome | Meaning |
| --- | --- |
| `AUTO_MATCH` | Candidate meets the selected confidence and margin thresholds, passes financial and quality controls, is within the amount cap, and is not otherwise flagged. This is a recommendation only; no payment is posted. |
| `REVIEW` | A candidate needs human confirmation, for example because of a partial payment, missing usable reference, anomaly, low margin, high value, model outage, or probability below the auto threshold. |
| `EXCEPTION` | The payment cannot be matched safely, is a duplicate, fails a financial invariant, has no candidate, or falls below the review threshold. |

The profiles in `reconpilot/config.py` express policy assumptions:

| Profile | Maximum tolerated wrong-link rate for threshold selection | Minimum margin | Automatic amount cap |
| --- | ---: | ---: | ---: |
| `fast_close` | 2.0% | 0.10 | ₹100,000 |
| `balanced` | 1.0% | 0.20 | ₹50,000 |
| `control_first` | 0.5% | 0.35 | ₹20,000 |

Threshold selection uses validation B and requires at least 20 validation examples at a candidate threshold. If no threshold meets the profile's constraint, the resulting threshold prevents automatic matches. The test set is not used to select these thresholds.

Settlement checks include:

- Observed net equals gross minus fee, tax, and refund within ₹1.00.
- Refund is between zero and gross.
- Fee and tax are nonnegative.
- Total deductions do not exceed gross, and observed net is nonnegative.
- When an invoice is assigned, payment gross does not exceed the invoice amount beyond the configured tolerance.

## Explainability and audit trail

For a model-backed assigned candidate, the response includes LightGBM feature contributions with labels and whether each feature supports or lowers the match score. It also returns a deterministic text explanation, settlement proof, policy rule, candidate list, and anomaly/duplicate flags. Explanations describe a decision; they do not control it.

Each accepted reconciliation request is written to `artifacts/audit.db` with its request payload, decision summary, timestamp, and a SHA-256 hash chained to the previous row. SQLite triggers reject ordinary updates and deletes, and `GET /v1/audit/verify` checks the stored chain. This is an integrity check for the prototype, not tamper-proof storage: a person with direct database access can alter the database.

**Privacy warning:** audit records include the submitted request, which may contain customer identifiers, names, references, and amounts. The API rejects card-number-like values in selected text fields, but that is not a substitute for production data protection. Use only simulated or otherwise safe test data.

## API and dashboard

Start the API and open `http://127.0.0.1:8000`. FastAPI's interactive API documentation is at `http://127.0.0.1:8000/docs`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service and loaded-state/model status |
| `GET` | `/v1/models/active` | Active model, profiles, and headline evaluation metrics |
| `GET` | `/v1/demo/scenarios` | Available simulated cases |
| `POST` | `/v1/demo/run` | Run one demo scenario |
| `POST` | `/v1/reconcile/case` | Reconcile one submitted payment |
| `POST` | `/v1/reconcile/batch` | Reconcile up to 500 payments with global assignment |
| `GET` | `/v1/invoices?merchant_id=M1` | List invoices for a synthetic merchant |
| `POST` | `/v1/invoices` | Add an in-memory invoice for a demo |
| `GET` | `/v1/metrics/model-performance` | Evaluation report, dataset card, and model manifest |
| `GET` | `/v1/audit?limit=20` | Read recent audit records |
| `GET` | `/v1/audit/verify` | Verify the audit hash chain |
| `POST` | `/v1/replay/{audit_id}` | Re-run a stored request and compare its decision |

The dashboard has **Reconcile**, **Evaluation**, and **Audit** views. It can use demo scenarios or manual input and can simulate model unavailability. There are no screenshots committed; run the app to view the current UI.

In **Manual entry**, submitting a payment adds it to the running server process's payment history after its audit record is written. Subsequent manual or batch reconciliations can use that history for duplicate and recent-payment checks. This in-memory transaction history is lost on server restart; the SQLite audit record persists locally but is not a durable payment ledger. The existing synthetic invoices shown beside the form are candidate reference data, not payments. The optional **Add a demo invoice** action also changes only the in-memory invoice catalog.

## Project structure

```text
ReckonPilot/
├── backend/
│   └── main.py                 # FastAPI app, request validation, routes, audit API
├── data/
│   ├── invoices.parquet        # Simulated invoices
│   ├── payments.parquet        # Simulated payments
│   ├── lineage.parquet         # Ground-truth links for evaluation
│   └── pairs.parquet           # Precomputed candidate features
├── models/
│   └── bundle.joblib           # Frozen model, calibrator, and thresholds
├── reconpilot/
│   ├── assign.py               # Global one-to-one assignment
│   ├── baselines.py            # Exact and fuzzy matchers
│   ├── config.py               # Data, feature, merchant, and policy settings
│   ├── controls.py             # Deterministic financial and anomaly checks
│   ├── explain.py              # Decision explanation and evidence labels
│   ├── features.py             # Candidate features and history
│   ├── pipeline.py             # Matching decisions and evaluation metrics
│   ├── policy.py               # Ordered outcome policy and user-facing text
│   ├── service.py              # Reconciliation service
│   └── simulator.py            # Deterministic synthetic data generator
├── scripts/
│   └── run_experiments.py      # Training, validation, final test, and charts
├── frontend/
│   ├── src/                    # React dashboard
│   └── package.json
├── artifacts/
│   ├── charts/                 # Evaluation charts
│   ├── eval_json/              # Dataset card and validation report
│   └── manifest.json           # Model/run metadata
├── tests/
│   ├── test_api.py
│   └── test_core.py
└── requirements.txt
```

## Run locally

The repository includes the simulated Parquet data and a frozen model bundle, so you do not need to train the model just to start the API.

### Prerequisites

- Python compatible with the pinned dependencies in `requirements.txt`
- Node.js and npm to build the dashboard (use a Vite-supported Node.js release)

### Install and start

From the repository root, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then open:

- Dashboard: <http://127.0.0.1:8000>
- API documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

If the state files or model bundle are missing, the API reports that state is unavailable. Regenerate the simulated data and model using the experiment runner before retrying.

## Experiments and evaluation

Run from the repository root:

```powershell
# Refit matchers and regenerate the repeatable validation report
python -m scripts.run_experiments

# Rebuild simulated data, then refit and evaluate
python -m scripts.run_experiments --regen

# Evaluate the held-out test set once and create the evaluation lock
python -m scripts.run_experiments --final
```

`--regen` replaces the generated data and rebuilds derived candidate features. The experiment runner also updates model and evaluation artifacts. Review the working tree before keeping those outputs. Once a final test lock exists, `--regen` refuses to replace the data associated with that test result; use a fresh checkout for a new generated benchmark.

`--final` is intentionally one-shot. It exits without re-evaluating if `artifacts/test_eval.lock` already exists. Do not remove that lock merely to rerun test evaluation; use the validation workflow for iterative changes, and preserve the held-out test set for a final measurement.

## Tests

Run the Python suite from the repository root:

```powershell
python -m pytest -q
```

Build the dashboard:

```powershell
cd frontend
npm ci
npm run build
```

The Python tests cover deterministic data generation, feature leakage protections, financial invariants, policy outcomes, one-to-one assignment, batch reconciliation, API validation, duplicate handling, model-outage behavior, audit verification, and replay.

Latest local verification: 30 Python tests passed; the run emitted one Starlette deprecation warning about its `httpx`-based `TestClient`. The frontend production build completed successfully with `npm run build`.

## Limitations and handoff notes

- **Synthetic-only evaluation:** test and validation scores are from a controlled simulator. No claim is made about Razorpay, bank, UPI, or real merchant traffic.
- **One incorrect automatic match in the current LightGBM test snapshot:** the measured result is not error-free. Any real deployment would require independent data, operational controls, monitoring, and human approval appropriate to the business.
- **No processor integration or financial execution:** this app returns reconciliation decisions only.
- **No authentication or authorization:** the API and dashboard are intended for local evaluation only.
- **Audit privacy:** the audit database stores submitted request data, including names/identifiers when supplied. Do not use sensitive production data.
- **Prototype persistence:** audit records use a local SQLite database. Newly added invoices and manual or batch payment history are held in process memory and do not survive a restart.
- **Thresholds are assumptions:** the profiles encode simulated wrong-link tolerances and amount caps; they are not approved financial policy.
- **No committed UI screenshots:** use the local dashboard to inspect the current interface.

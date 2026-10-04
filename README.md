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
- [ML pipeline](#ml-pipeline)
- [Model and evaluation results](#model-and-evaluation-results)
- [Decision engine](#decision-engine)
- [Explainability](#explainability)
- [Audit trail](#audit-trail)
- [External validation: DBLP–ACM](#external-validation-dblp-acm)
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

## ML pipeline

```text
reconpilot/simulator.py  → data/invoices.parquet, payments.parquet, lineage.parquet
reconpilot/features.py → time-safe invoice candidates + 24 payment/invoice features
scripts/run_experiments.py
  → exact/fuzzy baselines + Logistic Regression + LightGBM candidates
  → sigmoid calibration on validation A
  → policy thresholds selected on validation B
  → one-shot held-out test report + frozen model bundle
reconpilot/service.py + pipeline.py → scoring + one-to-one batch assignment + controls + policy decision
backend/main.py → validated API request + hash-chained audit record
frontend/src/ → reconciliation receipt + benchmark + audit views
```

The checked-in `models/bundle.joblib` contains the fitted LightGBM model, sigmoid calibrator, feature list, and validation-selected thresholds. The API can start without retraining.

**No test leakage:** payment days 0–48 are used for training, 49–55 for validation A (model/imbalance selection and calibration), 56–62 for validation B (operating-threshold selection), and day 63 onward for the held-out test. The test set is not used for model selection or threshold tuning. `--final` evaluates it once and writes `artifacts/test_eval.lock`; the runner refuses to rerun that final test or regenerate its data in the same workspace.

## Model and evaluation results

All results below are on the **held-out simulated test set** (2,650 payments; 46,054 candidate pairs). Model thresholds were selected on validation data, not on this test set. Matchers are compared using the balanced policy profile.

| Matcher | Pair PR-AUC | Top-1 accuracy | Auto precision | Straight-through recall | F1 | Auto-match rate | Not auto-matched |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Exact rules | 0.747 | 84.72% | 100.00% | 68.31% | 0.812 | 65.47% | 915 |
| Fuzzy heuristic | 0.880 | 93.89% | 100.00% | 13.31% | 0.235 | 12.75% | 2,312 |
| Logistic Regression | 0.989 | 95.17% | 100.00% | 82.91% | 0.907 | 79.47% | 544 |
| **LightGBM (serving model)** | **0.992** | **95.55%** | **99.95%** | **83.23%** | **0.908** | **79.81%** | **535** |

**Operational-efficiency result:** LightGBM left **535 of 2,650 payments** not automatically matched—**380 fewer cases (41.5%) than exact rules** on this test. Compared with Logistic Regression, it left 9 fewer. “Not auto-matched” combines review and exception outcomes; this is a workload proxy, **not a measured labor or rupee-cost saving**. The project does not assign costs to reviewing, resolving exceptions, or incorrect matches, so it does not claim a monetary cost reduction.

**Operating threshold:** for the balanced profile, the auto-match score cutoff was selected on validation B as the lowest threshold meeting the configured maximum 1% wrong-link rate among auto-match candidates, subject to at least 20 candidates. The selected cutoff is approximately **0.2525**, with a 0.20 minimum score margin and a ₹50,000 auto-match cap. The held-out test then measured 99.95% precision among auto-match recommendations and 83.23% straight-through recall.

Pair PR-AUC measures ranking among generated candidates; Top-1 accuracy measures whether the highest-ranked candidate is the correct invoice. Auto precision measures the share of auto-match recommendations that are correct and pass the safety checks. Straight-through recall measures the share of eligible payments correctly recommended for automatic matching.

The Evaluation tab shows this saved offline benchmark. Manual demo entries do not update these metrics because they have no verified ground-truth labels. Results describe performance on the simulator's held-out data, not real payment traffic.

## Decision engine

Candidate ranking does not decide the outcome on its own. The service assigns candidates (one-to-one for batches), then checks financial integrity, duplicate history, data quality, payment completeness, anomalies, confidence, margin, and the configured amount cap. The policy is deterministic and uses first-match-wins ordering:

| Priority | Rule | Condition | Outcome |
| ---: | --- | --- | --- |
| 1 | `DUPLICATE_PAYMENT` | Same merchant/customer/payer/amount/reference was received within one day | `EXCEPTION` |
| 2 | `FINANCIAL_CHECK_FAIL` | A settlement or invoice-amount invariant fails | `EXCEPTION` |
| 3 | `NO_CANDIDATE_MATCH` | No invoice was assigned | `EXCEPTION` |
| 4 | `SOLVER_UNAVAILABLE_REVIEW` | Global assignment solver failed | `REVIEW` |
| 5 | `NO_CONFIDENT_MATCH` | Score is below the review threshold | `EXCEPTION` |
| 6 | `DATA_QUALITY_LOW` | No usable payment reference | `REVIEW` |
| 7 | `PARTIAL_PAYMENT_REVIEW` | Payment is less than the invoice balance | `REVIEW` |
| 8 | `ANOMALY_REVIEW` | Fee rate or settlement delay is unusual | `REVIEW` |
| 9 | `MODEL_UNAVAILABLE_REVIEW` / `BELOW_AUTO_THRESHOLD` | Score is below the auto threshold (outage fallback or normal model mode) | `REVIEW` |
| 10 | `LOW_MARGIN_REVIEW` | Best candidate does not exceed the next candidate by the required margin | `REVIEW` |
| 11 | `HIGH_VALUE_REVIEW` | Payment exceeds the selected profile's amount cap | `REVIEW` |
| 12 | `AUTO_MATCH` | Every earlier control passes | `AUTO_MATCH` recommendation |

Every outcome is a **recommendation only**; the app cannot post or move funds. If model-outage simulation is enabled, the model is bypassed and exact rules are used; this test switch is not an indication that the loaded model is unavailable.

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

## Explainability

For a model-backed assigned candidate, the response includes the top five LightGBM `pred_contrib` feature contributions, their input values, and whether each contribution raises or lowers the model's raw score. This is model-derived evidence—not SHAP output, a calibrated probability decomposition, or causal proof. In model-outage mode, there are no model contributions; the exact-rule result is labelled separately.

The receipt also includes a deterministic explanation template, ranked candidate details, policy rule, duplicate/anomaly flags, and settlement arithmetic. The explanation describes the computed outcome; it cannot change it. The UI explicitly labels the narrative as a template.

## Audit trail

Each successfully reconciled request is written to `artifacts/audit.db` with the request payload, decision summary, timestamp, and a SHA-256 hash chained to the previous row. SQLite triggers reject ordinary updates and deletes; `GET /v1/audit/verify` checks the chain, and `POST /v1/replay/{audit_id}` reruns a stored request to compare its decision with the recorded one. Replay is not a payment action.

This is a local prototype integrity check, not tamper-proof or production storage: a person with direct database access can alter the database. Audit records contain submitted request data, which may include customer identifiers, names, references, and amounts. The API rejects card-number-like values in selected text fields, but this is not a substitute for production data protection; do not use sensitive production data.

## External validation: DBLP–ACM

An additional method check uses the public DBLP–ACM entity-matching benchmark (scholarly publication records). It tests whether text/entity-matching approaches can retrieve and rank known record pairs on a separate real-record dataset. It is **not payment data**, does not include merchant/payment behavior, and does not externally validate the payment model or its financial policy.

The optional `scripts/benchmark_check.py` experiment creates the top 10 ACM-title candidates per DBLP record without using labels for candidate retrieval, builds title/author/venue/year features, and trains separate Logistic Regression and LightGBM matchers. Publication-year quantiles define chronological train/validation/test partitions. The saved run contains 3,460 held-out candidate pairs covering 190 matched DBLP records; candidate recall at 10 is 100%.

| Matcher | Pair PR-AUC (95% bootstrap CI) | Top-1 accuracy |
| --- | ---: | ---: |
| Exact title | 0.6987 (0.6550–0.7549) | 93.16% |
| Fuzzy title/authors | 0.8220 (0.7529–0.8920) | 97.89% |
| Logistic Regression | 0.9712 (0.9332–0.9983) | 98.42% |
| LightGBM | 0.9955 (0.9871–0.9998) | 98.42% |

These are results of a **separate benchmark experiment**, not live data and not evidence that the payment model generalizes to payment-processor records. The source CSVs are not bundled. To reproduce the check, obtain the DBLP–ACM benchmark data from its publisher, place `DBLP2.csv`, `ACM.csv`, and `DBLP-ACM_perfectMapping.csv` under `data/benchmark/`, then run `python scripts/benchmark_check.py`. The script writes `artifacts/eval_json/benchmark.json`.

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
│   ├── run_experiments.py      # Training, validation, final test, and charts
│   └── benchmark_check.py      # Separate DBLP–ACM entity-matching method check
├── frontend/
│   ├── src/                    # React dashboard
│   └── package.json
├── artifacts/
│   ├── charts/                 # Evaluation charts
│   ├── eval_json/              # Dataset card and saved evaluation reports
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

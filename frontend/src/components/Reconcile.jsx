import { useEffect, useState } from "react";
import { api, post } from "../api";
import { inr } from "../utils";
import Result from "./Result";
import PolicyPanel from "./PolicyPanel";

const blankPayment = {
  merchant_id: "M1",
  amount: "",
  method: "upi",
  reference: "",
  narration: "",
  customer_id: "",
  payer_name: "",
  payment_time: "",
  fee: "",
  fee_tax: "",
  refund: "0",
  observed_net: "",
  settlement_lag_days: "",
  payment_id: "",
};

const blankInvoice = { customer_name: "", amount: "", customer_id: "" };

export default function Reconcile({ active }) {
  const [mode, setMode] = useState("demo");
  const [scenarios, setScenarios] = useState([]);
  const [scenarioError, setScenarioError] = useState("");
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [seed, setSeed] = useState(0);
  const [profile, setProfile] = useState("balanced");
  const [modelOff, setModelOff] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [payment, setPayment] = useState(blankPayment);
  const [invoices, setInvoices] = useState([]);
  const [invoiceState, setInvoiceState] = useState("idle");
  const [invoiceError, setInvoiceError] = useState("");
  const [invoiceForm, setInvoiceForm] = useState(blankInvoice);
  const [showInvoiceForm, setShowInvoiceForm] = useState(false);
  const [invoiceNotice, setInvoiceNotice] = useState("");

  useEffect(() => {
    api("/v1/demo/scenarios")
      .then(setScenarios)
      .catch((e) => setScenarioError(e.message));
  }, []);

  useEffect(() => {
    if (active?.default_payment_time) {
      setPayment((current) =>
        current.payment_time
          ? current
          : { ...current, payment_time: active.default_payment_time },
      );
    }
  }, [active]);

  useEffect(() => {
    if (mode !== "manual") return;

    let cancelled = false;
    setInvoiceState("loading");
    setInvoiceError("");

    api(`/v1/invoices?merchant_id=${encodeURIComponent(payment.merchant_id)}&limit=6`)
      .then((rows) => {
        if (!cancelled) {
          setInvoices(rows);
          setInvoiceState("ready");
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setInvoiceError(e.message);
          setInvoiceState("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [mode, payment.merchant_id]);

  const updatePayment = (key) => (event) => {
    const value = event.target.value;
    setPayment((current) => ({ ...current, [key]: value }));
    setResult(null);
    setError("");
  };

  const runDemo = async (scenarioId, nextSeed = 0) => {
    setError("");
    setResult(null);
    setBusy(true);
    setSelectedScenario(scenarioId);
    setSeed(nextSeed);

    try {
      setResult(
        await post("/v1/demo/run", {
          scenario_id: scenarioId,
          seed: nextSeed,
          profile,
          model_off: modelOff,
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const submitPayment = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);

    const numberOrNull = (value) => (value === "" ? null : Number(value));
    try {
      const response = await post("/v1/reconcile/case", {
        ...payment,
        amount: Number(payment.amount),
        fee: numberOrNull(payment.fee),
        fee_tax: numberOrNull(payment.fee_tax),
        refund: numberOrNull(payment.refund) ?? 0,
        observed_net: numberOrNull(payment.observed_net),
        settlement_lag_days: numberOrNull(payment.settlement_lag_days),
        payment_time: payment.payment_time || null,
        payment_id: payment.payment_id || null,
        profile,
        model_off: modelOff,
      });
      setResult(response);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addInvoice = async (event) => {
    event.preventDefault();
    setInvoiceError("");
    setInvoiceNotice("");
    setBusy(true);

    try {
      const created = await post("/v1/invoices", {
        merchant_id: payment.merchant_id,
        customer_name: invoiceForm.customer_name,
        amount: Number(invoiceForm.amount),
        customer_id: invoiceForm.customer_id,
      });
      setInvoiceForm(blankInvoice);
      setPayment((current) => ({
        ...current,
        reference: created.invoice_id,
        customer_id: invoiceForm.customer_id,
        payer_name: invoiceForm.customer_name,
      }));
      setInvoiceNotice(
        `${created.invoice_id} added to this running demo. It will be lost when the server restarts.`,
      );
      const rows = await api(
        `/v1/invoices?merchant_id=${encodeURIComponent(payment.merchant_id)}&limit=6`,
      );
      setInvoices(rows);
      setInvoiceState("ready");
    } catch (e) {
      setInvoiceError(e.message);
      setInvoiceState("error");
    } finally {
      setBusy(false);
    }
  };

  const useInvoiceAsReference = (invoice) => {
    setPayment((current) => ({
      ...current,
      reference: invoice.invoice_id,
      customer_id: invoice.customer_id,
      payer_name: invoice.customer_name,
    }));
    setResult(null);
    setInvoiceNotice(
      `${invoice.invoice_id} is reference data only. Enter the new incoming payment amount separately.`,
    );
  };

  const merchants = Object.entries(active?.merchants || { M1: "Aurora Electronics" });

  return (
    <>
      <div className="workbench">
        <aside className="workbench-rail">
          <section className="rail-section">
            <div className="eyebrow">01 / Workflow</div>
            <h2>Choose a starting point</h2>
            <p className="muted">
              Demo cases use generated transactions. Manual entry submits a new
              payment for reconciliation.
            </p>
            <div className="mode-switch" aria-label="Reconciliation mode">
              <button
                className={mode === "demo" ? "selected" : ""}
                type="button"
                onClick={() => {
                  setMode("demo");
                  setResult(null);
                  setError("");
                }}
              >
                <span className="mode-number">01</span>
                <span>
                  <b>Explore a scenario</b>
                  <small>Simulated sample data</small>
                </span>
                <span aria-hidden="true">↗</span>
              </button>
              <button
                className={mode === "manual" ? "selected" : ""}
                type="button"
                onClick={() => {
                  setMode("manual");
                  setResult(null);
                  setError("");
                }}
              >
                <span className="mode-number">02</span>
                <span>
                  <b>Enter a new payment</b>
                  <small>Fresh input, not an existing row</small>
                </span>
                <span aria-hidden="true">↗</span>
              </button>
            </div>
          </section>

          <section className="rail-section rail-policy">
            <div className="eyebrow">02 / Decision settings</div>
            <label htmlFor="policy-profile">Policy profile</label>
            <select
              id="policy-profile"
              value={profile}
              onChange={(event) => {
                setProfile(event.target.value);
                setResult(null);
              }}
            >
              <option value="fast_close">Fast-close</option>
              <option value="balanced">Balanced</option>
              <option value="control_first">Control-first</option>
            </select>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={modelOff}
                onChange={(event) => {
                  setModelOff(event.target.checked);
                  setResult(null);
                }}
              />
              <span>
                <b>Simulate model outage</b>
                <small>Test fallback rules; model remains loaded</small>
              </span>
            </label>
            <div className="rail-safety">
              <span aria-hidden="true">i</span>
              <p>
                Every outcome is a recommendation. This demo does not post
                payments or update an accounting system.
              </p>
            </div>
          </section>
        </aside>

        <main className="workbench-main">
          {mode === "demo" ? (
            <section className="panel-card">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">Generated examples</div>
                  <h2>Explore reconciliation scenarios</h2>
                </div>
                <span className="data-tag">SIMULATED DATA</span>
              </div>
              <p className="muted panel-intro">
                Each case is selected from the local synthetic dataset and
                passed through the same reconciliation pipeline.
              </p>
              {scenarioError && (
                <div className="notice error" role="alert">
                  Could not load scenarios: {scenarioError}
                </div>
              )}
              <div className="scenario-grid">
                {scenarios.map((scenario) => (
                  <button
                    key={scenario.id}
                    className={`scenario-card ${selectedScenario === scenario.id ? "selected" : ""}`}
                    type="button"
                    disabled={busy}
                    onClick={() => runDemo(scenario.id)}
                  >
                    <span className="scenario-meta">
                      <span>{scenario.available} examples</span>
                      <span aria-hidden="true">↗</span>
                    </span>
                    <b>{scenario.title}</b>
                    <span className="muted">{scenario.description}</span>
                  </button>
                ))}
              </div>
              {selectedScenario && (
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => runDemo(selectedScenario, seed + 1)}
                >
                  {busy ? "Running…" : "Load another example"}
                </button>
              )}
            </section>
          ) : (
            <section className="manual-layout">
              <form className="panel-card payment-form" onSubmit={submitPayment}>
                <div className="panel-heading">
                  <div>
                    <div className="eyebrow">New record / Payment</div>
                    <h2>Reconcile a new incoming payment</h2>
                  </div>
                  <span className="data-tag">NOT YET SUBMITTED</span>
                </div>
                <p className="muted panel-intro">
                  These details are submitted as a new payment input. Existing
                  invoices shown alongside are candidate references only; they
                  are not payment entries.
                </p>

                <div className="form-section">
                  <div className="form-section-title">
                    <span>01</span>
                    <b>Payment details</b>
                  </div>
                  <div className="field-grid">
                    <label>
                      Merchant
                      <select
                        value={payment.merchant_id}
                        onChange={updatePayment("merchant_id")}
                      >
                        {merchants.map(([id, name]) => (
                          <option key={id} value={id}>
                            {name} ({id})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Payment amount (₹) *
                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        required
                        value={payment.amount}
                        onChange={updatePayment("amount")}
                        placeholder="e.g. 5,000.00"
                      />
                    </label>
                    <label>
                      Payment method
                      <select
                        value={payment.method}
                        onChange={updatePayment("method")}
                      >
                        {["upi", "card", "netbanking", "wallet"].map((method) => (
                          <option key={method} value={method}>
                            {method}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Payment time
                      <input
                        type="datetime-local"
                        value={payment.payment_time?.slice(0, 16) || ""}
                        onChange={updatePayment("payment_time")}
                      />
                    </label>
                    <label>
                      Payment ID <span className="optional">optional</span>
                      <input
                        value={payment.payment_id}
                        onChange={updatePayment("payment_id")}
                        placeholder="Generated if left blank"
                        maxLength={128}
                      />
                    </label>
                  </div>
                </div>

                <div className="form-section">
                  <div className="form-section-title">
                    <span>02</span>
                    <b>Reference and payer</b>
                  </div>
                  <div className="field-grid">
                    <label>
                      Invoice / bank reference
                      <input
                        value={payment.reference}
                        onChange={updatePayment("reference")}
                        placeholder="Reference from the payment record"
                        maxLength={512}
                      />
                    </label>
                    <label>
                      Customer ID <span className="optional">optional</span>
                      <input
                        value={payment.customer_id}
                        onChange={updatePayment("customer_id")}
                        maxLength={128}
                      />
                    </label>
                    <label>
                      Payer name <span className="optional">optional</span>
                      <input
                        value={payment.payer_name}
                        onChange={updatePayment("payer_name")}
                        maxLength={256}
                      />
                    </label>
                    <label>
                      Bank narration <span className="optional">optional</span>
                      <input
                        value={payment.narration}
                        onChange={updatePayment("narration")}
                        maxLength={1024}
                      />
                    </label>
                  </div>
                </div>

                <details className="advanced-fields">
                  <summary>Settlement details <span>Optional</span></summary>
                  <div className="field-grid">
                    <label>
                      Gateway fee (₹)
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={payment.fee}
                        onChange={updatePayment("fee")}
                        placeholder="Merchant contract rate"
                      />
                    </label>
                    <label>
                      Fee tax (₹)
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={payment.fee_tax}
                        onChange={updatePayment("fee_tax")}
                        placeholder="18% of fee if blank"
                      />
                    </label>
                    <label>
                      Refund (₹)
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={payment.refund}
                        onChange={updatePayment("refund")}
                      />
                    </label>
                    <label>
                      Observed net settlement (₹)
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={payment.observed_net}
                        onChange={updatePayment("observed_net")}
                        placeholder="Calculated if blank"
                      />
                    </label>
                    <label>
                      Settlement lag (days)
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={payment.settlement_lag_days}
                        onChange={updatePayment("settlement_lag_days")}
                        placeholder="Merchant's typical lag if blank"
                      />
                    </label>
                  </div>
                </details>

                <div className="form-footer">
                  <p>
                    Submitting scores this new payment against the selected
                    merchant's invoice candidates. After a successful audit
                    write, the payment joins this running process's history for
                    later duplicate checks; it is not a permanent transaction
                    ledger and resets when the server restarts.
                  </p>
                  <button className="button button-primary" disabled={busy}>
                    {busy ? "Reconciling…" : "Run reconciliation"}
                    <span aria-hidden="true">→</span>
                  </button>
                </div>
              </form>

              <aside className="panel-card invoice-rail">
                <div className="eyebrow">Reference data / Existing invoices</div>
                <h2>Invoice candidates</h2>
                <p className="muted">
                  These are existing synthetic invoices used only to find a
                  possible match for your new payment.
                </p>

                {invoiceState === "loading" && (
                  <p className="muted">Loading invoice candidates…</p>
                )}
                {invoiceState === "error" && (
                  <div className="notice error" role="alert">
                    Could not load invoices: {invoiceError}
                  </div>
                )}
                {invoiceState === "ready" && invoices.length === 0 && (
                  <p className="empty-state">
                    No invoice candidates were returned for this merchant.
                  </p>
                )}
                {invoiceNotice && (
                  <div className="notice" role="status">{invoiceNotice}</div>
                )}

                <div className="invoice-list">
                  {invoices.map((invoice) => (
                    <button
                      className="invoice-option"
                      key={invoice.invoice_id}
                      type="button"
                      onClick={() => useInvoiceAsReference(invoice)}
                    >
                      <span className="invoice-option-top">
                        <b>{invoice.invoice_id}</b>
                        <span>{inr(invoice.amount)}</span>
                      </span>
                      <span className="muted">
                        {invoice.customer_name} · {invoice.customer_id}
                      </span>
                      <span className="invoice-use">Use reference only ↗</span>
                    </button>
                  ))}
                </div>

                <div className="invoice-create">
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => setShowInvoiceForm((shown) => !shown)}
                    aria-expanded={showInvoiceForm}
                  >
                    {showInvoiceForm ? "− Close" : "+ Add a demo invoice"}
                  </button>
                  {showInvoiceForm && (
                    <form onSubmit={addInvoice}>
                      <p className="muted">
                        This adds invoice reference data to the current server
                        process only. It is not saved to disk and disappears
                        when the server restarts.
                      </p>
                      <label>
                        Customer name
                        <input
                          required
                          value={invoiceForm.customer_name}
                          onChange={(event) =>
                            setInvoiceForm((current) => ({
                              ...current,
                              customer_name: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label>
                        Invoice amount (₹)
                        <input
                          required
                          type="number"
                          min="0.01"
                          step="0.01"
                          value={invoiceForm.amount}
                          onChange={(event) =>
                            setInvoiceForm((current) => ({
                              ...current,
                              amount: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <label>
                        Customer ID <span className="optional">optional</span>
                        <input
                          value={invoiceForm.customer_id}
                          onChange={(event) =>
                            setInvoiceForm((current) => ({
                              ...current,
                              customer_id: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        className="button button-secondary button-full"
                        disabled={busy}
                      >
                        Add to demo catalog
                      </button>
                    </form>
                  )}
                </div>
              </aside>
            </section>
          )}

          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          {!result && !error && (
            <div className="result-placeholder">
              <span className="placeholder-mark">R</span>
              <div>
                <div className="eyebrow">Decision workspace</div>
                <h2>Your result will appear here</h2>
                <p className="muted">
                  {mode === "manual"
                    ? "Enter a new payment and run reconciliation to see candidate invoices, financial checks, and the decision explanation."
                    : "Select a generated scenario to inspect the complete reconciliation output."}
                </p>
              </div>
            </div>
          )}
          {result && <Result res={result} />}
        </main>
      </div>

      {active?.profiles && <PolicyPanel active={active} />}
    </>
  );
}

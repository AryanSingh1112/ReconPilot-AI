import { useEffect, useState } from "react";
import { api, apiArray, post } from "../api";
import "./settlement.css";

const inr = (v) => (v == null ? "—" : "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

export default function Settlement() {
  const [mode, setMode] = useState("demo");
  const [scen, setScen] = useState([]);
  const [sel, setSel] = useState(null);
  const [seed, setSeed] = useState(0);
  const [profile, setProfile] = useState("balanced");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [merchants, setMerchants] = useState({});
  const [merchant, setMerchant] = useState("M1");
  const [batches, setBatches] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [credit, setCredit] = useState("");

  useEffect(() => {
    apiArray("/v1/settlements/scenarios").then(setScen).catch((e) => setErr(e.message));
    api("/v1/models/active").then((a) => setMerchants(a.merchants || {})).catch(() => {});
  }, []);
  useEffect(() => {
    if (mode !== "manual") return;
    apiArray(`/v1/settlements/batches?merchant_id=${merchant}`).then((b) => {
      setBatches(b);
      if (b.length) { setBatchId(b[0].batch_id); setCredit(String(b[0].statement_total)); }
    }).catch((e) => setErr(e.message));
  }, [mode, merchant]);

  const runDemo = async (id, s) => {
    setErr(""); setSel(id); setSeed(s);
    try { setRes(await post("/v1/settlements/demo", { scenario_id: id, seed: s, profile })); } catch (e) { setErr(e.message); }
  };
  const submit = async () => {
    setErr("");
    try { setRes(await post("/v1/settlements/credit", { batch_id: batchId, credit: Number(credit), profile })); } catch (e) { setErr(e.message); }
  };
  const pickBatch = (id) => {
    setBatchId(id);
    const b = batches.find((x) => x.batch_id === id);
    if (b) setCredit(String(b.statement_total));
  };

  return (
    <div className="sp-wrap">
      <div className="sp-card">
        <h3>Bank credit to reconcile</h3>
        <div className="sp-body">
          <div className="sp-seg">
            <button className={"sp-btn" + (mode === "demo" ? " on" : "")} onClick={() => setMode("demo")}>Demo scenarios</button>
            <button className={"sp-btn" + (mode === "manual" ? " on" : "")} onClick={() => setMode("manual")}>Manual credit</button>
          </div>
          <p className="sp-note">Simulated payouts. Arithmetic and search only; no model is used in this layer.</p>
          <label>Policy profile</label>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="fast_close">Fast-close</option><option value="balanced">Balanced</option><option value="control_first">Control-first</option>
          </select>
          {mode === "demo" ? (
            <div style={{ marginTop: 10 }}>
              {scen.map((s) => (
                <button key={s.id} className={"sp-scen" + (sel === s.id ? " on" : "")} onClick={() => runDemo(s.id, 0)}>
                  <b>{s.title}</b><span>{s.description}</span>
                </button>
              ))}
              {sel && <button className="sp-btn" onClick={() => runDemo(sel, seed + 1)}>Try another batch</button>}
            </div>
          ) : (
            <div>
              <label>Merchant</label>
              <select value={merchant} onChange={(e) => setMerchant(e.target.value)}>
                {Object.entries(merchants).map(([k, v]) => <option key={k} value={k}>{k} · {v}</option>)}
              </select>
              <label>Settlement batch</label>
              <select value={batchId} onChange={(e) => pickBatch(e.target.value)}>
                {batches.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.settle_date} · {b.n_payments} payments · {inr(b.statement_total)}</option>)}
              </select>
              <label>Bank credit received (₹)</label>
              <input value={credit} onChange={(e) => setCredit(e.target.value)} />
              <p className="sp-note">Prefilled with the gateway statement total. Subtract one payment's net or a round amount to test a shortfall.</p>
              <button className="sp-btn primary" onClick={submit}>Reconcile credit</button>
            </div>
          )}
        </div>
      </div>
      <div>
        {err && <div className="sp-err">{err}</div>}
        {!res && !err && <div className="sp-card"><div className="sp-body">Pick a scenario or enter a credit.</div></div>}
        {res && <SettlementResult res={res} />}
      </div>
    </div>
  );
}

function SettlementResult({ res }) {
  const p = res.proof, ex = res.explanation;
  return (
    <>
      <div className="sp-card">
        <h3>Credit decision{res.scenario ? ` · ${res.scenario.title}` : ""}</h3>
        <div className="sp-body">
          <div className={"sp-action sp-" + res.action}><h2>{res.action}</h2><p>{res.action_text}</p></div>
          <div className="sp-tiles">
            <div className="sp-tile"><small>Bank credit</small><b>{inr(p.bank_credit)}</b></div>
            <div className="sp-tile"><small>Gateway statement</small><b>{inr(p.statement_net)}</b></div>
            <div className="sp-tile"><small>Credit minus statement</small><b className={p.credit_pass ? "sp-pass" : "sp-fail"}>{inr(p.credit_vs_statement)}</b></div>
          </div>
          <div className="sp-rule"><span className="sp-code">{res.rule}</span><p style={{ margin: "6px 0 0" }}>{res.rule_text}</p></div>
          <p className="sp-note">Batch {res.batch_id} · {res.merchant_id} · settled {res.settle_date} · {res.n_payments} payments · profile {res.profile} · audit saved: {String(res.audit_persisted)}</p>
        </div>
      </div>
      <div className="sp-card">
        <h3>Settlement proof (computed, not predicted)</h3>
        <div className="sp-body">
          <table className="sp-table"><tbody>
            <tr><td>Gross payments</td><td className="r">{inr(p.gross)}</td></tr>
            <tr><td>− Gateway fees</td><td className="r">{inr(p.fees)}</td></tr>
            <tr><td>− Fee tax</td><td className="r">{inr(p.tax)}</td></tr>
            <tr><td>− Refunds</td><td className="r">{inr(p.refunds)}</td></tr>
            <tr className="sp-total"><td>= Contract net</td><td className="r">{inr(p.contract_net)}</td></tr>
            <tr><td>Gateway statement (sum of reported nets)</td><td className="r">{inr(p.statement_net)}</td></tr>
            <tr><td>Statement minus contract (tolerance {inr(res.thresholds.tolerance)})</td>
              <td className={"r " + (p.statement_pass ? "sp-pass" : "sp-fail")}>{inr(p.statement_vs_contract)} {p.statement_pass ? "PASS" : "FAIL"}</td></tr>
            <tr><td>Bank credit</td><td className="r">{inr(p.bank_credit)}</td></tr>
            <tr><td>Credit minus statement (tolerance {inr(res.thresholds.tolerance)})</td>
              <td className={"r " + (p.credit_pass ? "sp-pass" : "sp-fail")}>{inr(p.credit_vs_statement)} {p.credit_pass ? "PASS" : "FAIL"}</td></tr>
          </tbody></table>
        </div>
      </div>
      <div className="sp-card">
        <h3>Why this decision?</h3>
        <div className="sp-body">
          <div className="sp-box"><h4>Variance explanation (computed). Cannot change the decision.</h4>
            <p style={{ margin: 0 }}>{ex.message}</p>
            {ex.n_solutions > 1 && <ul>{ex.alternatives.map((a, i) => <li key={i}>{a.join(", ")}</li>)}</ul>}
            {ex.truncated && <p className="sp-note">Search was limited to a bounded pool of payments.</p>}
          </div>
          <div className="sp-box"><h4>Summary (template)</h4><p style={{ margin: 0 }}>{res.summary.text}</p></div>
          <p style={{ marginTop: 12 }}><b>Payments in this batch</b></p>
          <div className="sp-scroll">
            <table className="sp-table"><thead><tr><th>Payment</th><th className="r">Gross</th><th className="r">Contract net</th><th className="r">Reported net</th><th className="r">Variance</th></tr></thead>
              <tbody>{res.payments.map((x) => (
                <tr key={x.payment_id} className={x.explained ? "sp-hit" : x.short ? "sp-short" : ""}>
                  <td>{x.payment_id}{x.explained ? " ◀ explains variance" : ""}</td><td className="r">{inr(x.amount)}</td>
                  <td className="r">{inr(x.expected_net)}</td><td className="r">{inr(x.observed_net)}</td>
                  <td className={"r " + (x.short ? "sp-fail" : "")}>{inr(x.variance)}</td></tr>))}</tbody></table>
          </div>
        </div>
      </div>
    </>
  );
}
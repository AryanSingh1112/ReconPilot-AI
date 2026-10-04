import { downloadDecisionReceipt, inr, pct, f3 } from "../utils";

export default function Result({ res }) {
  const assignedCandidate = res.candidates.find((candidate) => candidate.assigned);
  const outcomeTitle = {
    AUTO_MATCH: "Candidate match recommended",
    REVIEW: "Human review required",
    EXCEPTION: "Investigate before matching",
  }[res.action] || res.action;
  const maxc = Math.max(
    0.0001,
    ...res.evidence.map((e) => Math.abs(e.contribution))
  );

  return (
    <>
      <section className={`decision-receipt ${res.action}`}>
        <div className="receipt-topline">
          <div>
            <div className="eyebrow">
              Decision receipt / {res.scenario ? "Generated scenario" : "New payment"}
            </div>
            <h2>{res.scenario?.title || res.payment_id}</h2>
          </div>
          <button
            className="button button-secondary receipt-download"
            type="button"
            onClick={() => downloadDecisionReceipt(res)}
          >
            <span aria-hidden="true">↓</span> Download decision record
          </button>
        </div>

        {res.mode === "simulated_outage" && (
          <div className="notice warning">
            Simulated outage is enabled for this test. The model is bypassed
            for this decision; exact deterministic rules are used instead.
          </div>
        )}
        {res.mode === "model_unavailable" && (
          <div className="notice warning">
            Model bundle unavailable: exact deterministic rules are used for
            this decision; everything else goes to review.
          </div>
        )}

        <div className="receipt-verdict">
          <div className="verdict-main">
            <span className="verdict-kicker">SYSTEM RECOMMENDATION</span>
            <span className={`verdict-code ${res.action}`}>{res.action}</span>
            <h3>{outcomeTitle}</h3>
            <p>{res.action_text}</p>
            <div className="receipt-rule">
              <code>{res.rule}</code>
              <span>{res.rule_text}</span>
            </div>
          </div>
          <div className="verdict-side">
            <div className="human-control">
              <span className="human-control-icon" aria-hidden="true">Ⅱ</span>
              <span>
                <b>Human-controlled</b>
                <small>No payment posted</small>
              </span>
            </div>
            <div className="matched-invoice">
              <span className="receipt-label">ASSIGNED INVOICE</span>
              {assignedCandidate ? (
                <>
                  <b className="invoice-id">{assignedCandidate.invoice_id}</b>
                  <span>{assignedCandidate.customer}</span>
                  <strong>{inr(assignedCandidate.amount)}</strong>
                </>
              ) : (
                <b className="no-invoice">No invoice assigned</b>
              )}
            </div>
            <div className="receipt-audit">
              <span className={`audit-indicator ${res.audit_persisted ? "is-saved" : ""}`} />
              {res.audit_persisted ? "Decision recorded in audit log" : "Audit record not confirmed"}
            </div>
          </div>
        </div>

        <div className="receipt-metrics">
          <div className="receipt-metric">
            <div className="metric-head">
              <span className="receipt-label">MATCH CONFIDENCE</span>
              <b>{res.mode === "normal" ? pct(res.probability) : "RULE-BASED"}</b>
            </div>
            {res.mode === "normal" && (
              <div
                className="confidence-track"
                role="meter"
                aria-label="Match confidence"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={Math.round(Math.min(1, Math.max(0, res.probability)) * 100)}
              >
                <span style={{ width: `${Math.min(100, Math.max(0, res.probability * 100))}%` }} />
              </div>
            )}
            <small>
              {res.mode === "normal"
                ? "Calibrated candidate probability"
                : res.mode === "simulated_outage"
                  ? "Simulated outage; exact rules only"
                  : "The model was not used"}
            </small>
          </div>
          <div className="receipt-metric">
            <span className="receipt-label">LEAD OVER NEXT CANDIDATE</span>
            <b>{f3(res.margin)}</b>
            <small>Score margin used by the policy</small>
          </div>
          <div className="receipt-metric">
            <span className="receipt-label">SETTLEMENT CHECKS</span>
            <b className={res.checks.every((check) => check.pass) ? "pass" : "fail"}>
              {res.checks.filter((check) => check.pass).length}/{res.checks.length} PASS
            </b>
            <small>Deterministic arithmetic, not model output</small>
          </div>
        </div>
        <div className="receipt-bottom">
          <span>PAYMENT <b>{res.payment_id}</b></span>
          <span>AMOUNT <b>{inr(res.amount)}</b></span>
          <span>MODEL <b>{res.model}</b></span>
          <span>PROFILE <b>{res.profile}</b></span>
          <span>
            MODE{" "}
            <b>
              {res.mode === "normal"
                ? "MODEL + POLICY"
                : res.mode === "simulated_outage"
                  ? "SIMULATED OUTAGE · EXACT RULES"
                  : "MODEL UNAVAILABLE · EXACT RULES"}
            </b>
          </span>
        </div>
        <p className="receipt-disclaimer">
          This recommendation is not a posting instruction or payment approval.
          Verify the source records and follow your authorized review process.
        </p>
      </section>

      <div className="two">
        <div className="card">
          <h3>Settlement proof · deterministic checks</h3>
          <div className="body">
            <div className="settlement-equation">
              <div>
                <small>GROSS PAYMENT</small>
                <b>{inr(res.proof.gross)}</b>
              </div>
              <span>−</span>
              <div>
                <small>FEE + TAX + REFUND</small>
                <b>{inr(res.proof.fee + res.proof.tax + res.proof.refund)}</b>
              </div>
              <span>=</span>
              <div>
                <small>EXPECTED NET</small>
                <b>{inr(res.proof.expected_net)}</b>
              </div>
            </div>
            <table className="proof">
              <tbody>
                <tr><td>Gateway fee</td><td className="r">{inr(res.proof.fee)}</td></tr>
                <tr><td>Fee tax</td><td className="r">{inr(res.proof.tax)}</td></tr>
                <tr><td>Refund</td><td className="r">{inr(res.proof.refund)}</td></tr>
                <tr><td>Observed net</td><td className="r">{inr(res.proof.observed_net)}</td></tr>
                <tr>
                  <td>Net difference (tolerance {inr(res.proof.tolerance)})</td>
                  <td className={`r ${(res.proof.net_pass ?? res.proof.pass) ? "pass" : "fail"}`}>
                    {inr(res.proof.difference)} · {(res.proof.net_pass ?? res.proof.pass) ? "PASS" : "FAIL"}
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="check-list">
              {res.checks.map((check) => (
                <div key={check.id}>
                  <code>{check.id}</code>
                  <span>{check.name}</span>
                  <b className={check.pass ? "pass" : "fail"}>{check.pass ? "PASS" : "FAIL"}</b>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="card candidate-card">
          <h3>Candidate comparison · ranked by match score</h3>
          <div className="body">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th><th>Customer</th><th className="r">Invoice amount</th>
                  <th>Reference</th><th className="r">Match score</th>
                </tr>
              </thead>
              <tbody>
                {res.candidates.map((candidate) => (
                  <tr className={candidate.assigned ? "assigned-candidate" : ""} key={candidate.invoice_id}>
                    <td>{candidate.invoice_id}{candidate.assigned ? " ✓" : ""}</td>
                    <td>{candidate.customer}</td>
                    <td className="r">{inr(candidate.amount)}</td>
                    <td>{candidate.reference_match}</td>
                    <td className="r">
                      {res.mode === "normal" ? pct(candidate.probability) : f3(candidate.probability)}
                    </td>
                  </tr>
                ))}
                {!res.candidates.length && (
                  <tr><td colSpan="5">No plausible candidate invoice.</td></tr>
                )}
              </tbody>
            </table>
            {res.candidates.length > 0 && (
              <p className="muted">
                Candidate scores are not financial verification. The selected
                recommendation also depends on policy, assignment, and
                settlement controls.
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Why this recommendation? · model evidence and policy context</h3>

        <div className="body">
          {res.evidence.length > 0 && (
            <>
              <p>
                <b>Top model contributing factors</b>
              </p>

              <ul>
                {res.evidence.map((e) => (
                  <li key={e.id}>
                    {e.label} ({e.value ?? "missing"}){" "}
                    <span
                      className={
                        e.effect === "supports_match" ? "up" : "down"
                      }
                    >
                      {e.effect === "supports_match"
                        ? "supports the match"
                        : "lowers the match"}
                    </span>
                  </li>
                ))}
              </ul>

              {res.evidence.map((e) => {
                const w = (Math.abs(e.contribution) / maxc) * 50;

                return (
                  <div key={e.id}>
                    {e.label}

                    <div className="bar">
                      <i
                        style={{
                          left:
                            e.contribution > 0
                              ? "50%"
                              : `${50 - w}%`,
                          width: `${w}%`,
                          background:
                            e.contribution > 0
                              ? "#16a34a"
                              : "#dc2626",
                        }}
                      />
                    </div>
                  </div>
                );
              })}

              <p className="muted">
                Contributions are from the LightGBM raw output, not the
                calibrated probability shown above. They describe this
                candidate only and do not determine the policy outcome.
              </p>
            </>
          )}

          <div className="two">
            <div className="box">
              <h4>Computed checks and flags</h4>

              <div>
                Fee flag: {String(res.flags.fee_unusual)}
              </div>

              <div>
                Delay flag: {String(res.flags.delay_unusual)}
              </div>

              <div>
                Duplicate flag: {String(res.flags.dup)}
              </div>

              <div>
                Thresholds: review{" "}
                {res.thresholds.review?.toFixed?.(2)} · auto{" "}
                {res.thresholds.auto?.toFixed?.(2)} · min margin{" "}
                {res.thresholds.min_margin}
              </div>
            </div>

            <div className="box">
              <h4>
                Explanation ({res.explanation.provider}). Cannot change the
                decision.
              </h4>

              <p style={{ margin: 0 }}>
                {res.explanation.summary}
              </p>

              {res.explanation.uncertainties.length > 0 && (
                <ul>
                  {res.explanation.uncertainties.map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
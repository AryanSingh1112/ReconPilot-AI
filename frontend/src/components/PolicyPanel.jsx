import { inr, pct } from "../utils";

export default function PolicyPanel({ active }) {
  const p = active.profiles;
  const h = active.headline;

  return (
    <div className="card">
      <h3>Model &amp; policy</h3>
      <div className="body">
        <div className="tiles">
          <div className="tile">
            <small>Model</small>
            <b>{active.model}</b>
          </div>

          <div className="tile">
            <small>Auto-match threshold (balanced)</small>
            <b>{p.balanced.auto.toFixed(3)}</b>
          </div>

          <div className="tile">
            <small>Features</small>
            <b>{active.n_features}</b>
          </div>
        </div>

        <p className="note">
          Thresholds come from this simulator's validation run. A match outcome
          is a recommendation only—not an instruction to post or move funds.
        </p>

        {h && (
          <p>
            Measured on the {h.source} set: precision{" "}
            <b>{pct(h.precision)}</b> · straight-through recall{" "}
            <b>{pct(h.recall)}</b> · F1 <b>{pct(h.f1)}</b> · auto-match rate{" "}
            <b>{pct(h.auto_rate)}            </b> · wrong-link auto-match recommendation{" "}
            <b>{pct(h.incorrect_auto_post)}</b>
          </p>
        )}

        <table>
          <thead>
            <tr>
              <th>Rule (first match wins)</th>
              <th>Condition</th>
              <th>Action</th>
            </tr>
          </thead>

          <tbody>
            <tr>
              <td>
                <code>DUPLICATE_PAYMENT</code>
              </td>
              <td>identical payment within 1 day</td>
              <td>EXCEPTION</td>
            </tr>

            <tr>
              <td>
                <code>FINANCIAL_CHECK_FAIL</code>
              </td>
              <td>any invariant fails</td>
              <td>EXCEPTION</td>
            </tr>

            <tr>
              <td>
                <code>NO_CANDIDATE_MATCH</code>
              </td>
              <td>no invoice assigned</td>
              <td>EXCEPTION</td>
            </tr>

            <tr>
              <td>
                <code>SOLVER_UNAVAILABLE_REVIEW</code>
              </td>
              <td>global assignment fails</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>NO_CONFIDENT_MATCH</code>
              </td>
              <td>p &lt; {p.balanced.review}</td>
              <td>EXCEPTION</td>
            </tr>

            <tr>
              <td>
                <code>DATA_QUALITY_LOW</code>
              </td>
              <td>no usable reference</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>PARTIAL_PAYMENT_REVIEW</code>
              </td>
              <td>payment is below invoice amount</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>ANOMALY_REVIEW</code>
              </td>
              <td>unusual fee or delay</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>MODEL_UNAVAILABLE_REVIEW</code>
              </td>
              <td>model outage and probability below fallback threshold</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>BELOW_AUTO_THRESHOLD</code>
              </td>
              <td>p &lt; auto threshold</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>LOW_MARGIN_REVIEW</code>
              </td>
              <td>margin &lt; {p.balanced.min_margin}</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>HIGH_VALUE_REVIEW</code>
              </td>
              <td>amount &gt; {inr(p.balanced.cap / 100)}</td>
              <td>REVIEW</td>
            </tr>

            <tr>
              <td>
                <code>AUTO_MATCH</code>
              </td>
              <td>all earlier safety and policy rules pass</td>
              <td>RECOMMEND MATCH</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
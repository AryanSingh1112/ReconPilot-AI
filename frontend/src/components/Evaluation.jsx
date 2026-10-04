import { useEffect, useState } from "react";
import { api } from "../api";
import { inr, pct, ci, f3 } from "../utils";

export default function Evaluation() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/v1/metrics/model-performance")
      .then(setD)
      .catch((e) => setError(e.message));
  }, []);

  if (!d)
    return (
      <div className="card">
        <div className="body">
          {error ? (
            <div className="notice error" role="alert">
              Could not load evaluation results: {error}
            </div>
          ) : (
            "Loading evaluation results…"
          )}
        </div>
      </div>
    );

  const r = d.report;

  if (!r)
    return (
      <div className="card">
        <div className="body">
          Run <code>python -m scripts.run_experiments</code> to generate
          results.
        </div>
      </div>
    );

  const c = d.dataset_card;
  const benchmark = r.methods.lgbm?.decision;

  return (
    <>
      <section className="evaluation-intro">
        <div>
          <div className="eyebrow">Held-out benchmark / {r.split || d.source}</div>
          <h2>A match is only useful when it’s safe to act on.</h2>
          <p>
            We compare candidate ranking with the policy’s ability to keep
            unsafe matches out of automatic recommendations. This saved
            simulator run is a benchmark—not a live feed or a real-world
            performance claim.
          </p>
        </div>
        <div className="evaluation-snapshot" aria-label="LightGBM benchmark snapshot">
          <span className="eyebrow">LIGHTGBM · SIMULATED SNAPSHOT</span>
          <div>
            <strong>{benchmark ? pct(benchmark.auto_precision) : "—"}</strong>
            <span>auto-match precision</span>
          </div>
          <div>
            <strong>{benchmark ? pct(benchmark.straight_through_recall) : "—"}</strong>
            <span>eligible payments auto-matched</span>
          </div>
        </div>
      </section>

      <div className="notice">
        Demo payments are not used to calculate these benchmark metrics. They
        have no verified match labels, so charts such as precision–recall and
        calibration cannot be calculated honestly from them. The fixed charts
        are therefore not shown here.
      </div>

      <div className="panel-card">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">Matching performance</div>
            <h2>Matcher comparison</h2>
          </div>
          <span className="data-tag">SAME DECISION POLICY</span>
        </div>

        <p className="muted panel-intro">
          Pair PR-AUC measures candidate ranking. Automatic-match figures are
          simulator measurements—not a guarantee or a payment-posting result.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th className="r">Pair PR-AUC (95% CI)</th>
                <th className="r">Top-1 acc.</th>
                <th className="r">Auto rate</th>
                <th className="r">Auto precision (95% CI)</th>
                <th className="r">Straight-through recall</th>
                <th className="r">Wrong-link recommendation rate</th>
                <th className="r">Review</th>
                <th className="r">Exception</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(r.methods).map(([m, v]) => (
                <tr key={m}>
                  <td>
                    <b>{m}</b>
                  </td>

                  <td className="r">
                    {f3(v.pair_pr_auc)}
                    {ci(v.pair_pr_auc_ci95)}
                  </td>

                  <td className="r">{pct(v.top1_accuracy)}</td>

                  <td className="r">{pct(v.decision.auto_rate)}</td>

                  <td className="r">
                    {pct(v.decision.auto_precision)}
                    {ci(v.decision.auto_precision_ci95)}
                  </td>

                  <td className="r">
                    {pct(v.decision.straight_through_recall)}
                  </td>

                  <td className="r">
                    {pct(v.decision.incorrect_auto_post_rate)}
                  </td>

                  <td className="r">
                    {pct(v.decision.review_rate)}
                  </td>

                  <td className="r">
                    {pct(v.decision.exception_rate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="muted">
            LightGBM minus Logistic Regression, PR-AUC difference 95% CI:{" "}
            {ci(r.lgbm_minus_lr_pr_auc_ci95)}. If the interval includes 0, the
            difference is not distinguishable from noise.
          </p>
        </div>
      </div>

      <div className="two evaluation-grid">
        <div className="panel-card">
          <div className="eyebrow">LightGBM</div>
          <h2>Calibration</h2>

          <div className="panel-content">
            Brier raw {f3(r.calibration.brier_raw)} → calibrated{" "}
            {f3(r.calibration.brier_calibrated)}
            <br />
            ECE raw {f3(r.calibration.ece_raw)} → calibrated{" "}
            {f3(r.calibration.ece_calibrated)}
          </div>
        </div>

        <div className="panel-card">
          <div className="eyebrow">Pipeline</div>
          <h2>Candidate generation &amp; throughput</h2>

          <div className="panel-content">
            Candidate recall at limit 20:{" "}
            {pct(r.candidate_recall.at_limit)}
            <br />
            End-to-end batch:{" "}
            {Math.round(r.throughput.payments_per_minute)} payments/min (
            {r.throughput.payments} payments in{" "}
            {r.throughput.seconds.toFixed(1)} s)
          </div>
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Batch reconciliation</div>
        <h2>Global assignment vs independent top match</h2>

        <div className="panel-content">
          Greedy accuracy {pct(r.assignment.greedy_top1_accuracy)},
          payments sharing one invoice:{" "}
          {r.assignment.greedy_payments_sharing_an_invoice}
          <br />
          Hungarian accuracy {pct(r.assignment.hungarian_accuracy)},
          payments sharing one invoice:{" "}
          {r.assignment.hungarian_payments_sharing_an_invoice}
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Error analysis / LightGBM</div>
        <h2>Performance by reference quality</h2>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Reference style</th>
                <th className="r">Payments</th>
                <th className="r">Auto rate</th>
                <th className="r">Review</th>
                <th className="r">Exception</th>
                <th className="r">Auto precision</th>
                <th className="r">Wrong-link recommendation rate</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(r.slices_by_ref_style).map(([s, v]) => (
                <tr key={s}>
                  <td>
                    {s}
                    {s === "spaced" ? " (unseen in training)" : ""}
                  </td>

                  <td className="r">{v.n}</td>
                  <td className="r">{pct(v.auto_rate)}</td>
                  <td className="r">{pct(v.review_rate)}</td>
                  <td className="r">{pct(v.exception_rate)}</td>
                  <td className="r">{pct(v.auto_precision)}</td>
                  <td className="r">
                    {pct(v.incorrect_auto_post_rate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Policy comparison / LightGBM</div>
        <h2>Profile outcomes</h2>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th className="r">Auto rate</th>
                <th className="r">Review</th>
                <th className="r">Exception</th>
                <th className="r">Auto precision</th>
                <th className="r">Wrong-link recommendation rate</th>
                <th className="r">Amount in review</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(r.profiles).map(([p, v]) => (
                <tr key={p}>
                  <td>{p}</td>
                  <td className="r">{pct(v.auto_rate)}</td>
                  <td className="r">{pct(v.review_rate)}</td>
                  <td className="r">{pct(v.exception_rate)}</td>
                  <td className="r">{pct(v.auto_precision)}</td>
                  <td className="r">
                    {pct(v.incorrect_auto_post_rate)}
                  </td>
                  <td className="r">{inr(v.amount_in_review_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Failure review</div>
        <h2>Where errors are stopped—or reach auto-match</h2>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Risk</th>
                <th className="r">Payments</th>
                <th className="r">Stopped before auto-match</th>
                <th className="r">Reached auto-match recommendation</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(r.error_table).map(([k, v]) => (
                <tr key={k}>
                  <td>{k.replaceAll("_", " ")}</td>
                  <td className="r">{v.payments}</td>
                  <td className="r">{v.stopped_before_auto_post}</td>
                  <td className="r">{v.reached_auto_post}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Financial controls</div>
        <h2>Deterministic anomaly checks</h2>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th className="r">Actual</th>
                <th className="r">Flagged</th>
                <th className="r">Precision</th>
                <th className="r">Recall</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(r.anomaly_detection).map(([k, v]) => (
                <tr key={k}>
                  <td>{k.replaceAll("_", " ")}</td>
                  <td className="r">{v.actual}</td>
                  <td className="r">{v.flagged}</td>
                  <td className="r">{pct(v.precision)}</td>
                  <td className="r">{pct(v.recall)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel-card">
        <div className="eyebrow">Feature analysis</div>
        <h2>Feature-group ablation</h2>

        <div className="table-wrap">
          <table>
            <tbody>
              {Object.entries(r.ablation_val_b_pr_auc).map(([k, v]) => (
                <tr key={k}>
                  <td>{k.replaceAll("_", " ")}</td>
                  <td className="r">{f3(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {c && (
        <div className="panel-card">
          <div className="eyebrow">Provenance</div>
          <h2>Dataset card</h2>

          <div className="panel-content">
            {c.payments} payments · {c.invoices} invoices · {c.pairs}{" "}
            candidate pairs ({pct(c.pair_positive_rate)} true matches) ·{" "}
            {c.duplicates} duplicate payments
            <br />
            Payments per split:{" "}
            {Object.entries(c.split_payments)
              .map(([k, v]) => `${k} ${v}`)
              .join(" · ")}
            <br />
            Held-out reference style: {c.held_out_style} · data sha256:{" "}
            <code>{c.data_sha256.slice(0, 16)}…</code>
            <br />
            <p className="muted">{c.limitation}</p>
          </div>
        </div>
      )}
    </>
  );
}
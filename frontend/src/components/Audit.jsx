import { useEffect, useState } from "react";
import { api, apiArray, post } from "../api";
import { pct } from "../utils";

export default function Audit() {
  const [rows, setRows] = useState([]);
  const [verification, setVerification] = useState(null);
  const [replays, setReplays] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setError("");
    setBusy(true);
    try {
      setRows(await apiArray("/v1/audit?limit=50"));
    } catch (e) {
      setError(`Could not load the audit log: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const verifyChain = async () => {
    setError("");
    try {
      setVerification(await api("/v1/audit/verify"));
    } catch (e) {
      setError(`Could not verify the audit chain: ${e.message}`);
    }
  };

  const replay = async (id) => {
    setError("");
    setReplays((current) => ({ ...current, [id]: { loading: true } }));
    try {
      const result = await post(`/v1/replay/${id}`, {});
      setReplays((current) => ({ ...current, [id]: { result } }));
    } catch (e) {
      setReplays((current) => ({ ...current, [id]: { error: e.message } }));
    }
  };

  return (
    <section className="panel-card">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">Traceability / Local SQLite</div>
          <h2>Decision audit trail</h2>
        </div>
        <div className="audit-actions">
          <button className="button button-secondary" onClick={load} disabled={busy}>
            {busy ? "Refreshing…" : "↻ Refresh"}
          </button>
          <button className="button button-primary" onClick={verifyChain}>
            Verify hash chain
          </button>
        </div>
      </div>

      <p className="muted panel-intro">
        Reconciliation requests are recorded with their submitted fields and
        outcome. This prototype audit log is local to the server; it is not
        tamper-proof storage.
      </p>

      {verification && (
        <div className={`notice ${verification.valid ? "success" : "error"}`} role="status">
          {verification.valid
            ? `Hash chain valid · ${verification.rows} records checked`
            : `Hash chain broken at row ${verification.broken_at_row}`}
        </div>
      )}
      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Recorded</th>
              <th>Payment</th>
              <th>Recommendation</th>
              <th className="r">Probability</th>
              <th>Policy rule</th>
              <th>Input source</th>
              <th>Re-check</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const replayState = replays[row.id];
              return (
                <tr key={row.id}>
                  <td>{new Date(row.ts * 1000).toLocaleString()}</td>
                  <td>{row.payload.summary.payment_id}</td>
                  <td>
                    <span className={`table-outcome ${row.payload.summary.action}`}>
                      {row.payload.summary.action}
                    </span>
                  </td>
                  <td className="r">
                    {row.payload.summary.mode === "normal"
                      ? pct(row.payload.summary.probability)
                      : "n/a"}
                  </td>
                  <td><code>{row.payload.summary.rule}</code></td>
                  <td><span className="data-tag">{row.payload.source}</span></td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => replay(row.id)}
                      disabled={replayState?.loading}
                    >
                      {replayState?.loading ? "Checking…" : "Replay"}
                    </button>
                    {replayState?.result && (
                      <span className={replayState.result.reproduced ? "pass" : "fail"}>
                        {replayState.result.reproduced
                          ? "Reproduced"
                          : `Changed: ${JSON.stringify(replayState.result.diff)}`}
                      </span>
                    )}
                    {replayState?.error && (
                      <span className="fail">{replayState.error}</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {!busy && rows.length === 0 && !error && (
              <tr>
                <td colSpan="7">No reconciliation decisions have been recorded yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

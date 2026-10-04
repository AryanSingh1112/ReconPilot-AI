import { pct } from "../utils";

export default function Header({ health, active, activeError }) {
  const h = active?.headline;
  const ready = health?.state_loaded && health?.model_loaded;

  return (
    <header className="site-header">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">R</div>
        <div>
          <div className="brand-name">Reckon<span>Pilot</span></div>
          <div className="brand-caption">PAYMENT RECONCILIATION / LAB</div>
        </div>
      </div>
      <div className="header-right">
        <div className={`system-status ${ready ? "ready" : "not-ready"}`}>
          <span />
          {ready ? "Model & data ready" : health?.status === "down" ? "API unavailable" : "Model or data not ready"}
        </div>
        <div className="header-model">
          <span>MODEL</span>
          <b>{active?.model || (activeError ? "Unavailable" : "Loading…")}</b>
        </div>
        {h && (
          <div className="header-model">
            <span>{h.source.toUpperCase()} AUTO-MATCH PRECISION</span>
            <b>{pct(h.precision)}</b>
          </div>
        )}
      </div>
    </header>
  );
}
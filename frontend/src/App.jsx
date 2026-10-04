import { useEffect, useState } from "react";
import "./styles.css";

import { api } from "./api";
import Header from "./components/Header";
import Tabs from "./components/Tabs";
import Reconcile from "./components/Reconcile";
import Evaluation from "./components/Evaluation";
import Audit from "./components/Audit";

export default function App() {
  const [tab, setTab] = useState("reconcile");
  const [active, setActive] = useState(null);
  const [health, setHealth] = useState(null);
  const [activeError, setActiveError] = useState("");

  useEffect(() => {
    api("/health").then(setHealth).catch(() => setHealth({ status: "down" }));
    api("/v1/models/active")
      .then(setActive)
      .catch((e) => setActiveError(e.message));
  }, []);

  return (
    <div className="wrap">
      <Header health={health} active={active} activeError={activeError} />
      <div className="app-notice">
        <span className="app-notice-mark">!</span>
        <p>
          <b>Prototype workspace</b>
          <span>
            Sample records are synthetic. Manual inputs are recorded in the
            local audit log and held in memory for this run—do not enter real
            customer or payment data. No bank or processor is connected and no
            payment is posted.
          </span>
        </p>
      </div>
      <div className="navigation-row">
        <div>
          <div className="eyebrow">Workspace</div>
          <h2>{tab === "reconcile" ? "Reconciliation" : tab === "evaluation" ? "Model evaluation" : "Audit trail"}</h2>
        </div>
        <Tabs tab={tab} setTab={setTab} />
      </div>
      {activeError && (
        <div className="notice error" role="alert">
          Could not load model and merchant information: {activeError}
        </div>
      )}
      {tab === "reconcile" && <Reconcile active={active} />}
      {tab === "evaluation" && <Evaluation />}
      {tab === "audit" && <Audit />}
      <footer className="app-footer">
        RECKONPILOT <span>·</span> DECISION SUPPORT PROTOTYPE
      </footer>
    </div>
  );
}
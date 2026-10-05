export default function Tabs({ tab, setTab }) {
  return (
    <nav className="tabs" aria-label="Main navigation">
      {[
        ["reconcile", "Reconcile", "01"],
        ["settlement", "Settlements", "02"],
        ["evaluation", "Evaluation", "03"],
        ["audit", "Audit trail", "04"],
      ].map(([t, label, number]) => (
        <button
          key={t}
          className={tab === t ? "on" : ""}
          type="button"
          aria-current={tab === t ? "page" : undefined}
          onClick={() => setTab(t)}
        >
          <span>{number}</span>
          {label}
        </button>
      ))}
    </nav>
  );
}
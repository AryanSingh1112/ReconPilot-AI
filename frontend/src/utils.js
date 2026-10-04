export const inr = (v) =>
  v == null
    ? "—"
    : "₹" + Number(v).toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });

export const pct = (v) =>
  v == null ? "—" : (v * 100).toFixed(2) + "%";

export const ci = (a) =>
  a && a[0] != null
    ? ` (${a[0].toFixed(3)}–${a[1].toFixed(3)})`
    : "";

export const f3 = (v) =>
  v == null ? "—" : Number(v).toFixed(3);

export const downloadDecisionReceipt = (res) => {
  const receipt = {
    schema: "reckonpilot.decision-receipt.v1",
    generated_at: new Date().toISOString(),
    disclaimer:
      "Decision support only. This receipt is not a payment instruction, approval, or posting record.",
    payment: {
      payment_id: res.payment_id,
      amount_inr: res.amount,
      model: res.model,
      mode: res.mode,
      profile: res.profile,
    },
    recommendation: {
      action: res.action,
      text: res.action_text,
      policy_rule: res.rule,
      policy_reason: res.rule_text,
      assigned_invoice: res.assigned_invoice,
      match_probability: res.mode === "normal" ? res.probability : null,
      margin_to_next_candidate: res.margin,
      thresholds: res.thresholds,
      requires_human_verification: true,
      payment_posted: false,
    },
    settlement: {
      proof: res.proof,
      checks: res.checks,
      flags: res.flags,
    },
    candidates: res.candidates,
    model_evidence: res.evidence,
    explanation: res.explanation,
    audit: {
      persisted: Boolean(res.audit_persisted),
      note: "The audit status is not an operator approval or payment-posting status.",
    },
  };

  const blob = new Blob([JSON.stringify(receipt, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const paymentId = String(res.payment_id || "decision")
    .replace(/[^a-zA-Z0-9._-]/g, "_")
    .slice(0, 128);
  link.download = `reckonpilot-${paymentId}-receipt.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};
"""The Smart Form decision engine — deterministic, rule-driven, no LLM.

evaluate() walks an ordered rule list for the given service + complaint type
and returns the FIRST outcome whose condition matches, together with the
rule id and the full evaluation trace. The calling agent must treat the
result as final: the language model narrates and orchestrates, it never
decides.

Outcomes (from the Frontline Assist RFP):
  Auto-Resolve · Auto-Reject · AI-Assisted · Inform · Inform + B2B ·
  Cross-Service Handoff · Inform + Internal Follow-Up ·
  Inform + Accelerated Escalation
"""
from __future__ import annotations

from .data import INCOME_CAP_AED, expected_allowance


def _r(rule_id, condition, outcome, explanation, actions=None):
    return {"rule_id": rule_id, "condition": condition, "outcome": outcome,
            "explanation": explanation, "actions": actions or []}


def _rules_payment_not_received(f):
    salary = f.get("mohre_salary_aed")
    salary_s = f"{salary:,}" if salary is not None else "N/A"
    return [
        _r("IA-PN-01",
           f.get("payout_status") == "processed"
           and f.get("card_status") == "delivered",
           "Inform",
           "The July payment was processed and loaded to the delivered "
           "prepaid card. No fault found — share the payout date and the "
           "card's last four digits.",
           ["Share payout date and card reference",
            "Advise checking card balance via the FAB app or ATM"]),
        _r("IA-PN-02",
           f.get("payout_status") == "processed"
           and f.get("card_status") == "in_transit",
           "Inform + B2B",
           "Payment processed but the payment card is still with the courier. "
           "A business-to-business follow-up is sent to the card provider for "
           "delivery confirmation.",
           ["Send B2B follow-up to card provider with courier reference",
            "Share the delivery ETA with the beneficiary"]),
        _r("IA-PN-03",
           f.get("payout_status") == "on_hold_income_verification"
           and salary is not None and salary > INCOME_CAP_AED,
           "Auto-Reject",
           f"Verified household income exceeds the eligibility cap of "
           f"AED {INCOME_CAP_AED:,}. The hold converts to a rejection under "
           "the eligibility rules; an appeal window applies.",
           ["Issue rejection notice with appeal instructions"]),
        _r("IA-PN-04",
           f.get("payout_status") == "on_hold_income_verification"
           and salary is not None and salary <= INCOME_CAP_AED,
           "Auto-Resolve",
           f"Verified income AED {salary_s} is within the "
           f"AED {INCOME_CAP_AED:,} cap — the verification hold is cleared "
           "and the payment is released to the next payout run.",
           ["Clear income-verification hold",
            "Schedule payment in next payout run",
            "Notify beneficiary"]),
        _r("IA-PN-05",
           f.get("payout_status") == "on_hold_income_verification"
           and salary is None,
           "AI-Assisted",
           "Income verification is pending but the employment system is "
           "unreachable. Per the fallback policy the case proceeds with an "
           "AI-assisted document path: request a salary certificate and "
           "verify it through the document intelligence module.",
           ["Request salary certificate upload",
            "Verify via document intelligence (IDP)",
            "Re-evaluate on receipt"]),
        _r("IA-PN-06",
           f.get("payout_status") == "not_enrolled",
           "Inform",
           "No active enrollment exists for this service, so no payment is "
           "due. Explain the enrollment decision and how to re-apply.",
           ["Share enrollment status and re-application steps"]),
        _r("IA-PN-07", True,
           "Inform + Accelerated Escalation",
           "The payment state cannot be explained by the available data — "
           "escalate on the accelerated track with all evidence attached.",
           ["Escalate to payments operations (accelerated SLA)"]),
    ]


def _rules_amount_incorrect(f):
    dep = int(f.get("dependents_registered", 0))
    expected = expected_allowance(dep)
    received = f.get("received_amount_aed")
    received_s = f"{received:,}" if received is not None else "N/A"
    family = int(f.get("family_size", dep + 1))
    return [
        _r("IA-AM-01",
           received is not None and received == expected,
           "Auto-Resolve" if family - 1 <= dep else "Inform + Internal Follow-Up",
           f"The amount received (AED {received_s}) equals the formula amount "
           f"for {dep} registered dependents (base {500} + {300}/dependent). "
           + ("The complaint is resolved with the calculation breakdown."
              if family - 1 <= dep else
              f"However the household lists {family - 1} dependents while "
              f"only {dep} are registered — a registration follow-up is "
              "created so the amount can be corrected going forward."),
           ["Share the calculation breakdown"]
           + ([] if family - 1 <= dep else
              ["Create internal follow-up with Registration Operations"])),
        _r("IA-AM-02",
           received is not None and received != expected,
           "Inform + Accelerated Escalation",
           f"The amount received (AED {received_s}) does not match the "
           f"formula amount (AED {expected:,}) for the registered household — "
           "a payment discrepancy is escalated on the accelerated track.",
           ["Escalate discrepancy with both amounts attached"]),
        _r("IA-AM-03", True,
           "AI-Assisted",
           "The received amount is unknown — request the card statement via "
           "the document path, then re-evaluate.",
           ["Request card statement upload", "Re-evaluate on receipt"]),
    ]


def _rules_card_not_delivered(f):
    return [
        _r("IA-CD-01",
           f.get("card_status") == "in_transit",
           "Inform + B2B",
           "The card is with the courier. A B2B follow-up is sent to the "
           "card provider; the beneficiary receives the ETA and courier "
           "reference.",
           ["B2B follow-up to card provider", "Share ETA + courier reference"]),
        _r("IA-CD-02",
           f.get("card_status") == "delivered",
           "Inform + Accelerated Escalation",
           "The provider reports the card as delivered but the beneficiary "
           "disputes receipt — possible loss or misdelivery. Escalate for "
           "card block + reissue on the accelerated track.",
           ["Block card", "Reissue card", "Accelerated escalation"]),
        _r("IA-CD-03",
           f.get("card_status") == "not_issued",
           "Inform",
           "No card has been issued because there is no active enrollment or "
           "payment on the profile.",
           ["Explain issuance criteria"]),
        _r("IA-CD-04", True, "Inform + B2B",
           "Card state unclear — B2B status request to the provider.",
           ["B2B status request"]),
    ]


def _rules_eligibility_dispute(f):
    salary = f.get("mohre_salary_aed")
    salary_s = f"{salary:,}" if salary is not None else "N/A"
    return [
        _r("IA-EL-01",
           salary is not None and salary > INCOME_CAP_AED,
           "Auto-Reject",
           f"Verified income AED {salary_s} exceeds the AED "
           f"{INCOME_CAP_AED:,} cap — the rejection stands. Share the exact "
           "rule and the appeal channel.",
           ["Issue decision letter with rule citation and appeal steps"]),
        _r("IA-EL-02",
           salary is not None and salary <= INCOME_CAP_AED
           and f.get("enrollment_status") == "rejected",
           "Inform + Accelerated Escalation",
           "Verified income is within the cap yet the application was "
           "rejected — the decision is escalated for review with the "
           "verified data attached.",
           ["Escalate eligibility review (accelerated)"]),
        _r("IA-EL-03", f.get("mohre_salary_aed") is None,
           "AI-Assisted",
           "Income cannot be verified automatically — AI-assisted document "
           "path: request a salary certificate and verify via the document "
           "intelligence module.",
           ["Request salary certificate", "Verify via IDP", "Re-evaluate"]),
        _r("IA-EL-04", True, "Inform",
           "Eligibility conditions are met and enrollment is active — "
           "explain the current standing.",
           ["Share eligibility summary"]),
    ]


def _rules_swp(f, complaint_type):
    if complaint_type == "utility_support":
        return [
            _r("SWP-UT-01",
               f.get("utility_account") == "disconnected",
               "Cross-Service Handoff",
               "An active SWP beneficiary with a disconnected utility "
               "account qualifies for the utility-support service — the case "
               "is handed off to that service with consent.",
               ["Hand off to utility-support service", "Confirm consent"]),
            _r("SWP-UT-02", True, "Inform",
               "The utility account is active — no utility-support action "
               "is required.", ["Share account status"]),
        ]
    return [
        _r("SWP-GN-01",
           f.get("payout_status") == "processed",
           "Inform",
           "The SWP payment was processed on schedule — share the payout "
           "details.", ["Share payout details"]),
        _r("SWP-GN-02", True, "Inform + Internal Follow-Up",
           "SWP payment state requires an operations check — internal "
           "follow-up created.", ["Create internal follow-up"]),
    ]


_IA_TREES = {
    "payment_not_received": _rules_payment_not_received,
    "amount_incorrect": _rules_amount_incorrect,
    "card_not_delivered": _rules_card_not_delivered,
    "eligibility_dispute": _rules_eligibility_dispute,
}

COMPLAINT_TYPES = {
    "inflation_allowance": sorted(_IA_TREES.keys()),
    "swp": ["utility_support", "payment_not_received"],
}


def evaluate(service: str, complaint_type: str, facts: dict) -> dict:
    """Deterministic evaluation — first matching rule wins."""
    service = (service or "").strip().lower()
    complaint_type = (complaint_type or "").strip().lower()
    if service == "inflation_allowance":
        builder = _IA_TREES.get(complaint_type)
        if builder is None:
            return {"error": f"unknown complaint_type '{complaint_type}' — "
                             f"valid: {COMPLAINT_TYPES['inflation_allowance']}"}
        rules = builder(facts)
    elif service == "swp":
        rules = _rules_swp(facts, complaint_type)
    else:
        return {"error": "unknown service — valid: inflation_allowance, swp"}

    trace = []
    for rule in rules:
        matched = bool(rule["condition"])
        trace.append({"rule_id": rule["rule_id"], "matched": matched})
        if matched:
            return {
                "engine": "Smart Form decision engine (deterministic — no LLM)",
                "service": service, "complaint_type": complaint_type,
                "outcome": rule["outcome"],
                "rule_id": rule["rule_id"],
                "explanation": rule["explanation"],
                "required_actions": rule["actions"],
                "rule_trace": trace,
                "facts_used": facts,
            }
    return {"error": "no rule matched (tree misconfiguration)"}

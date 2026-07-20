"""Synthetic beneficiary & case data for the Frontline Assist demo.

Small, deterministic, and self-contained — profiles for the Inflation
Allowance and Social Welfare Program (SWP) complaint flows, plus a case
queue for the Case Management Agent. All identifiers are fictional.
"""
from __future__ import annotations

import copy

# Household income cap for Inflation Allowance eligibility (demo rule)
INCOME_CAP_AED = 25_000
# Monthly allowance formula (demo): base + per registered dependent (max 4)
IA_BASE_AED = 500
IA_PER_DEPENDENT_AED = 300


def expected_allowance(dependents_registered: int) -> int:
    return IA_BASE_AED + IA_PER_DEPENDENT_AED * min(int(dependents_registered), 4)


BENEFICIARIES = {
    "784-1985-6543210-2": {
        "emirates_id": "784-1985-6543210-2",
        "name": "Ahmed Al Mansoori", "name_ar": "أحمد المنصوري",
        "program": "inflation_allowance", "enrollment_status": "active",
        "family_size": 6, "dependents_registered": 4,
        "monthly_amount_aed": 1700,
        "payout_status": "processed", "payout_date": "2026-07-01",
        "card_status": "delivered", "card_last4": "4417",
        "mohre_salary_aed": 16500, "employment": "private sector",
        "gpssa_pension_aed": 0,
        "utility_account": "active", "ejari": "valid",
        "open_cases": [],
    },
    "784-1990-7654321-3": {
        "emirates_id": "784-1990-7654321-3",
        "name": "Noora Al Hammadi", "name_ar": "نورة الحمادي",
        "program": "inflation_allowance", "enrollment_status": "active",
        "family_size": 5, "dependents_registered": 3,
        "monthly_amount_aed": 1400,
        "payout_status": "on_hold_income_verification", "payout_date": None,
        "card_status": "delivered", "card_last4": "9032",
        # MoHRE integration is DOWN for this employer — triggers the
        # AI-document fallback path (salary certificate via IDP).
        "mohre_salary_aed": None, "employment": "private sector",
        "gpssa_pension_aed": 0,
        "utility_account": "active", "ejari": "valid",
        "open_cases": ["FA-2026-0142"],
    },
    "784-1978-1122334-5": {
        "emirates_id": "784-1978-1122334-5",
        "name": "Khalid Al Suwaidi", "name_ar": "خالد السويدي",
        "program": "inflation_allowance", "enrollment_status": "active",
        "family_size": 4, "dependents_registered": 2,
        "monthly_amount_aed": 1100,
        "payout_status": "processed", "payout_date": "2026-07-01",
        "card_status": "in_transit", "card_courier_ref": "FAB-DXB-88123",
        "card_eta": "2026-07-09",
        "mohre_salary_aed": 12800, "employment": "private sector",
        "gpssa_pension_aed": 0,
        "utility_account": "active", "ejari": "valid",
        "open_cases": [],
    },
    "784-1969-9988776-1": {
        "emirates_id": "784-1969-9988776-1",
        "name": "Mariam Al Zaabi", "name_ar": "مريم الزعابي",
        "program": "inflation_allowance", "enrollment_status": "active",
        "family_size": 7, "dependents_registered": 3,   # 2 more not registered
        "monthly_amount_aed": 1400,
        "payout_status": "processed", "payout_date": "2026-07-01",
        "card_status": "delivered", "card_last4": "2276",
        "mohre_salary_aed": 9800, "employment": "private sector",
        "gpssa_pension_aed": 0,
        "utility_account": "active", "ejari": "valid",
        "open_cases": ["FA-2026-0155"],
    },
    "784-1995-4455667-8": {
        "emirates_id": "784-1995-4455667-8",
        "name": "Salem Al Ketbi", "name_ar": "سالم الكتبي",
        "program": "inflation_allowance", "enrollment_status": "rejected",
        "family_size": 3, "dependents_registered": 1,
        "monthly_amount_aed": 0,
        "payout_status": "not_enrolled", "payout_date": None,
        "card_status": "not_issued",
        "mohre_salary_aed": 31200, "employment": "private sector",
        "gpssa_pension_aed": 0,
        "utility_account": "active", "ejari": "valid",
        "open_cases": [],
    },
    "784-1958-3344556-9": {
        "emirates_id": "784-1958-3344556-9",
        "name": "Fatima Al Shamsi", "name_ar": "فاطمة الشامسي",
        "program": "swp", "enrollment_status": "active",
        "family_size": 2, "dependents_registered": 0,
        "monthly_amount_aed": 3200,
        "payout_status": "processed", "payout_date": "2026-07-01",
        "card_status": "delivered", "card_last4": "7741",
        "mohre_salary_aed": 0, "employment": "retired",
        "gpssa_pension_aed": 4100,
        "utility_account": "disconnected",   # cross-service handoff material
        "ejari": "valid",
        "open_cases": [],
    },
}

CASES = {
    "FA-2026-0142": {
        "case_id": "FA-2026-0142", "emirates_id": "784-1990-7654321-3",
        "beneficiary": "Noora Al Hammadi",
        "service": "inflation_allowance",
        "complaint_type": "payment_not_received",
        "outcome": "AI-Assisted", "status": "awaiting_document",
        "sla_hours": 48, "age_hours": 39, "sla_breach": False,
        "timeline": [
            {"ts": "2026-07-06 09:12", "actor": "Customer Resolution Agent",
             "event": "Complaint registered — payment not received (July)"},
            {"ts": "2026-07-06 09:12", "actor": "Knowledge & Decision Agent",
             "event": "Payout on hold: income verification. MoHRE API unavailable "
                      "(maintenance) — deterministic engine routed to AI-Assisted"},
            {"ts": "2026-07-06 09:13", "actor": "Document Processing Agent",
             "event": "Salary certificate requested from beneficiary "
                      "(AI-document fallback path)"},
        ],
    },
    "FA-2026-0155": {
        "case_id": "FA-2026-0155", "emirates_id": "784-1969-9988776-1",
        "beneficiary": "Mariam Al Zaabi",
        "service": "inflation_allowance",
        "complaint_type": "amount_incorrect",
        "outcome": "Inform + Internal Follow-Up", "status": "with_operations",
        "sla_hours": 72, "age_hours": 80, "sla_breach": True,
        "timeline": [
            {"ts": "2026-07-03 14:02", "actor": "Customer Resolution Agent",
             "event": "Complaint registered — allowance amount lower than expected"},
            {"ts": "2026-07-03 14:03", "actor": "Knowledge & Decision Agent",
             "event": "2 of 5 dependents not registered in profile — amount "
                      "correct per formula; registration gap flagged (IA-AM-02)"},
            {"ts": "2026-07-03 14:04", "actor": "Case Management Agent",
             "event": "Internal follow-up created for Registration Operations"},
        ],
    },
    "FA-2026-0161": {
        "case_id": "FA-2026-0161", "emirates_id": "784-1958-3344556-9",
        "beneficiary": "Fatima Al Shamsi",
        "service": "swp",
        "complaint_type": "utility_support",
        "outcome": "Cross-Service Handoff", "status": "handed_off",
        "sla_hours": 48, "age_hours": 12, "sla_breach": False,
        "timeline": [
            {"ts": "2026-07-07 08:40", "actor": "Customer Resolution Agent",
             "event": "SWP beneficiary reports utility disconnection"},
            {"ts": "2026-07-07 08:41", "actor": "Knowledge & Decision Agent",
             "event": "Utility account disconnected — routed to utility-support "
                      "cross-service flow (SWP-UT-01)"},
        ],
    },
}

_case_seq = [170]


def new_case_id() -> str:
    _case_seq[0] += 1
    return f"FA-2026-{_case_seq[0]:04d}"


def get_beneficiary(emirates_id: str) -> dict | None:
    b = BENEFICIARIES.get(emirates_id.strip())
    return copy.deepcopy(b) if b else None


def find_beneficiary_by_name(name: str) -> dict | None:
    n = name.strip().lower()
    for b in BENEFICIARIES.values():
        if n in b["name"].lower() or n in b["name_ar"]:
            return copy.deepcopy(b)
    return None

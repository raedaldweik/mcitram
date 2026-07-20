"""Frontline Assist toolset — beneficiary profiles, mock government
integrations, the deterministic Smart Form engine, document-intelligence
consumption, and a lightweight case queue.

The integrations are mocks that answer instantly; one of them (MoHRE, for a
specific employer) is deliberately unavailable so the AI-document fallback
path can be demonstrated end to end.
"""
from __future__ import annotations

import re
from typing import Optional

from toolset import ToolSet

from . import data as D
from . import tree as T

frontline = ToolSet("frontline")


# ── profiles ────────────────────────────────────────────────────────
@frontline.add(
    "get_beneficiary_profile",
    "Look up a beneficiary profile by Emirates ID (784-XXXX-XXXXXXX-X) or by "
    "name. Returns program enrollment, family composition, payout & card "
    "status, and open cases. Always start a complaint flow here — the Smart "
    "Form engine is profile-aware.",
    {"type": "object",
     "properties": {"emirates_id": {"type": "string"},
                    "name": {"type": "string"}},
     "required": []},
)
async def get_beneficiary_profile(emirates_id: Optional[str] = None,
                                  name: Optional[str] = None):
    b = None
    if emirates_id:
        b = D.get_beneficiary(emirates_id)
    if b is None and name:
        b = D.find_beneficiary_by_name(name)
    if b is None:
        return {"error": "beneficiary not found",
                "hint": "known demo IDs: " + ", ".join(D.BENEFICIARIES)}
    return b


# ── mock real-time integrations (≤ 30s requirement — these answer instantly)
@frontline.add(
    "check_icp",
    "ICP (Federal Authority for Identity & Citizenship) — verify identity, "
    "family book and residency status for an Emirates ID.",
    {"type": "object", "properties": {"emirates_id": {"type": "string"}},
     "required": ["emirates_id"]},
)
async def check_icp(emirates_id: str):
    b = D.get_beneficiary(emirates_id)
    if not b:
        return {"system": "ICP", "status": "NOT_FOUND"}
    return {"system": "ICP", "status": "OK", "identity_verified": True,
            "family_size": b["family_size"],
            "dependents_registered": b["dependents_registered"],
            "response_ms": 240}


@frontline.add(
    "check_mohre",
    "MoHRE — verified private-sector employment and salary for an Emirates "
    "ID. May be unavailable during maintenance windows; on SERVICE_UNAVAILABLE "
    "use the AI-document fallback (salary certificate via IDP) instead of "
    "blocking the case.",
    {"type": "object", "properties": {"emirates_id": {"type": "string"}},
     "required": ["emirates_id"]},
)
async def check_mohre(emirates_id: str):
    b = D.get_beneficiary(emirates_id)
    if not b:
        return {"system": "MoHRE", "status": "NOT_FOUND"}
    if b["mohre_salary_aed"] is None:
        return {"system": "MoHRE", "status": "SERVICE_UNAVAILABLE",
                "error": "Employer record service in scheduled maintenance "
                         "window — retry after 4h",
                "fallback": "Request salary certificate and verify via the "
                            "document intelligence module (IDP)"}
    return {"system": "MoHRE", "status": "OK",
            "employment": b["employment"],
            "verified_salary_aed": b["mohre_salary_aed"], "response_ms": 310}


@frontline.add(
    "check_gpssa",
    "GPSSA — verified pension income for an Emirates ID.",
    {"type": "object", "properties": {"emirates_id": {"type": "string"}},
     "required": ["emirates_id"]},
)
async def check_gpssa(emirates_id: str):
    b = D.get_beneficiary(emirates_id)
    if not b:
        return {"system": "GPSSA", "status": "NOT_FOUND"}
    return {"system": "GPSSA", "status": "OK",
            "pension_aed": b["gpssa_pension_aed"], "response_ms": 190}


@frontline.add(
    "check_card_status",
    "Prepaid-card provider (FAB) — card issuance, delivery and last-load "
    "status for a beneficiary.",
    {"type": "object", "properties": {"emirates_id": {"type": "string"}},
     "required": ["emirates_id"]},
)
async def check_card_status(emirates_id: str):
    b = D.get_beneficiary(emirates_id)
    if not b:
        return {"system": "FAB Cards", "status": "NOT_FOUND"}
    out = {"system": "FAB Cards", "status": "OK",
           "card_status": b["card_status"], "response_ms": 280}
    for k in ("card_last4", "card_courier_ref", "card_eta"):
        if b.get(k):
            out[k] = b[k]
    if b["payout_status"] == "processed":
        out["last_load"] = {"date": b["payout_date"],
                            "amount_aed": b["monthly_amount_aed"]}
    return out


@frontline.add(
    "check_utility",
    "Utility provider — account standing for a beneficiary (used by SWP "
    "utility-support flows).",
    {"type": "object", "properties": {"emirates_id": {"type": "string"}},
     "required": ["emirates_id"]},
)
async def check_utility(emirates_id: str):
    b = D.get_beneficiary(emirates_id)
    if not b:
        return {"system": "Utility", "status": "NOT_FOUND"}
    return {"system": "Utility", "status": "OK",
            "account": b["utility_account"], "response_ms": 350}


# ── the Smart Form decision engine (deterministic) ──────────────────
@frontline.add(
    "evaluate_complaint",
    "The Smart Form decision engine — DETERMINISTIC and final; the language "
    "model must never override it. Pass the service "
    "(inflation_allowance | swp), the complaint_type "
    "(payment_not_received | amount_incorrect | card_not_delivered | "
    "eligibility_dispute | utility_support), and a facts object assembled "
    "from the profile and integration checks (payout_status, card_status, "
    "mohre_salary_aed or null when unavailable, dependents_registered, "
    "family_size, received_amount_aed, enrollment_status, utility_account). "
    "Returns one of the eight RFP outcomes with the rule id, the rule "
    "evaluation trace, and the required actions.",
    {"type": "object",
     "properties": {
         "service": {"type": "string"},
         "complaint_type": {"type": "string"},
         "facts": {"type": "object"}},
     "required": ["service", "complaint_type", "facts"]},
)
async def evaluate_complaint(service: str, complaint_type: str, facts: dict):
    return T.evaluate(service, complaint_type, facts or {})


# ── document intelligence (existing IDP — we only CONSUME it) ───────
@frontline.add(
    "submit_document_to_idp",
    "Submit an uploaded document to the existing document-intelligence "
    "module (IDP) and consume its result: extracted fields, confidence "
    "score, and rejection reason. Confidence < 0.70 means the document is "
    "not usable — give the beneficiary the re-upload guidance verbatim.",
    {"type": "object",
     "properties": {
         "document_name": {"type": "string"},
         "document_text": {"type": "string",
                           "description": "text of the attached document"}},
     "required": ["document_text"]},
)
async def submit_document_to_idp(document_text: str,
                                 document_name: str = "upload"):
    text = document_text or ""
    low = text.lower()
    if len(text.strip()) < 120:
        return {"idp": "Document Intelligence Module", "document": document_name,
                "confidence": 0.41, "accepted": False,
                "rejection_reason": "Low image quality — text could not be "
                                    "read reliably",
                "reupload_guidance": "Retake the photo in good lighting, flat "
                                     "on a dark surface, all four corners "
                                     "visible, no glare. PDF/JPG/PNG, max 10MB."}
    if "salary" in low or "راتب" in text:
        m = re.search(r"(?:AED|aed|د\.إ)?\s*([0-9]{1,3}(?:[,.][0-9]{3})+|[0-9]{4,6})",
                      text.replace("٬", ","))
        salary = int(re.sub(r"[^0-9]", "", m.group(1))) if m else None
        out = {"idp": "Document Intelligence Module", "document": document_name,
               "document_type": "salary_certificate", "confidence": 0.93,
               "accepted": True,
               "extracted_fields": {"gross_salary_aed": salary}}
        if salary is None:
            out.update(confidence=0.58, accepted=False,
                       rejection_reason="Document recognized as a salary "
                                        "certificate but no salary amount "
                                        "could be extracted",
                       reupload_guidance="Upload the full certificate page "
                                         "showing the gross salary figure.")
        return out
    return {"idp": "Document Intelligence Module", "document": document_name,
            "confidence": 0.62, "accepted": False,
            "rejection_reason": "Document type not recognized — expected a "
                                "salary certificate",
            "reupload_guidance": "Upload the employer-issued salary "
                                 "certificate (stamped), not a bank "
                                 "statement or ID copy."}


# ── case queue ──────────────────────────────────────────────────────
@frontline.add(
    "list_cases",
    "List cases in the Frontline Assist queue with outcome, status, SLA age "
    "and breach flag. Filter with status or sla_breach.",
    {"type": "object",
     "properties": {"status": {"type": "string"},
                    "sla_breach": {"type": "boolean"}},
     "required": []},
)
async def list_cases(status: Optional[str] = None,
                     sla_breach: Optional[bool] = None):
    rows = []
    for c in D.CASES.values():
        if status and c["status"] != status:
            continue
        if sla_breach is not None and c["sla_breach"] != sla_breach:
            continue
        rows.append({k: c[k] for k in
                     ("case_id", "beneficiary", "service", "complaint_type",
                      "outcome", "status", "sla_hours", "age_hours",
                      "sla_breach")})
    return {"total": len(rows), "cases": rows}


@frontline.add(
    "get_case_timeline",
    "Full audit timeline for a case — every inter-agent invocation with "
    "actor, event, and timestamp (the reasoning audit log).",
    {"type": "object", "properties": {"case_id": {"type": "string"}},
     "required": ["case_id"]},
)
async def get_case_timeline(case_id: str):
    c = D.CASES.get(case_id.strip().upper())
    return c or {"error": f"case {case_id} not found",
                 "known": list(D.CASES)}


@frontline.add(
    "create_case",
    "Create a case for outcomes that need follow-up (AI-Assisted, Inform + "
    "B2B, Cross-Service Handoff, Inform + Internal Follow-Up, Inform + "
    "Accelerated Escalation). Records the outcome, rule id and first "
    "timeline entries.",
    {"type": "object",
     "properties": {
         "emirates_id": {"type": "string"},
         "service": {"type": "string"},
         "complaint_type": {"type": "string"},
         "outcome": {"type": "string"},
         "rule_id": {"type": "string"},
         "summary": {"type": "string"}},
     "required": ["emirates_id", "service", "complaint_type", "outcome"]},
)
async def create_case(emirates_id: str, service: str, complaint_type: str,
                      outcome: str, rule_id: str = "", summary: str = ""):
    b = D.get_beneficiary(emirates_id)
    cid = D.new_case_id()
    D.CASES[cid] = {
        "case_id": cid, "emirates_id": emirates_id,
        "beneficiary": b["name"] if b else "(unknown)",
        "service": service, "complaint_type": complaint_type,
        "outcome": outcome, "status": "open",
        "sla_hours": 48, "age_hours": 0, "sla_breach": False,
        "timeline": [
            {"ts": "now", "actor": "Customer Resolution Agent",
             "event": f"Case created — {outcome}"
                      + (f" ({rule_id})" if rule_id else "")},
            *([{"ts": "now", "actor": "Knowledge & Decision Agent",
                "event": summary}] if summary else []),
        ],
    }
    return {"case_id": cid, "status": "open", "outcome": outcome}

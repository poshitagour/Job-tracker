# HR-focused job scoring for Poshita's Ireland Stamp 1G journey.
# Permit labels are triage signals only; actual eligibility depends on the role,
# SOC classification, salary, employer and DETE rules.
import re
from config.profile import PROFILE

HRIS_KWS = ["hris", "hr systems", "hr technology", "people systems", "workday", "successfactors", "oracle hcm", "ukg", "kronos", "workforce management", "wfm"]
ANALYTICS_KWS = ["people analytics", "workforce analytics", "workforce planning", "hr data", "power bi", "sql", "python", "dashboard", "data migration", "data validation", "reporting"]
PROJECT_KWS = ["project manager", "project management", "programme manager", "program manager", "transformation", "implementation", "uat", "raid", "system integrator", "system integration", "data migration", "vendor management", "stakeholder management", "ms project"]
HR_KWS = ["hr generalist", "hr advisor", "hr operations", "employee relations", "learning and development", "talent", "people operations", "human resources"]
ADMIN_KWS = ["hr administrator", "human resources administrator", "hr admin", "hr administration", "hr clerical", "recruitment administrator", "payroll administrator"]
CSEP_SIGNAL_KWS = ["it project and programme manager", "it project manager", "it business analyst", "systems analyst", "business analyst", "systems designer", "technology project manager", "hris project manager", "hr systems project manager", "software implementation"]

MID_MARKET_TARGETS = {
    "version 1", "bearingpoint", "fenergo", "liberty it", "guidewire", "teamwork", "tines", "ntt data",
    "cgi", "wayflyer", "glanbia", "musgrave", "daon", "dedalus", "druid software", "demonware"
}
HIGH_TIER_TARGETS = {
    "accenture", "deloitte", "ey", "pwc", "kpmg", "workday", "sap", "oracle", "hubspot", "salesforce",
    "stripe", "microsoft", "mastercard", "jpmorgan", "citi", "state street", "pfizer", "msd", "medtronic"
}


def _text(title, description):
    return f"{title} {description}".lower()


def get_company_tier(company: str) -> str:
    c = company.lower().strip()
    if any(x in c for x in MID_MARKET_TARGETS): return "B - Mid-market established"
    if any(x in c for x in HIGH_TIER_TARGETS): return "A - High-tier / highly competitive"
    return "C - Other / investigate"


def classify_permit_path(title: str, description: str, salary: str = "") -> dict:
    text = _text(title, description)
    if any(k in text for k in ADMIN_KWS):
        return {"path": "AVOID - HR administrative occupation signal", "confidence": "high", "reason": "Role appears administrative; HR administrative occupations are currently on the ineligible list."}
    if any(k in text for k in CSEP_SIGNAL_KWS) and any(k in text for k in HRIS_KWS + PROJECT_KWS):
        return {"path": "CSEP CANDIDATE - verify SOC/duties", "confidence": "medium", "reason": "Technology/project/system duties may align with an eligible Critical Skills occupation; verify actual SOC classification and salary."}
    if any(k in text for k in HRIS_KWS + ANALYTICS_KWS + PROJECT_KWS + HR_KWS):
        return {"path": "GEP CANDIDATE - check LMNT/occupation", "confidence": "medium", "reason": "Professional role appears potentially permit-eligible, but GEP requirements and Labour Market Needs Test may apply."}
    return {"path": "UNKNOWN - manual permit review", "confidence": "low", "reason": "Insufficient role detail to triage permit route."}


def calculate_fit_score(title: str, description: str) -> int:
    text = _text(title, description)
    score = 0
    # Strongest match: HRIS / transformation / project delivery
    for kw in HRIS_KWS:
        if kw in text: score += 10
    for kw in ANALYTICS_KWS:
        if kw in text: score += 7
    for kw in PROJECT_KWS:
        if kw in text: score += 8
    for kw in HR_KWS:
        if kw in text: score += 6
    for kw in ["dublin", "ireland", "hybrid", "immediate", "stakeholder", "vendor", "data governance", "change management"]:
        if kw in text: score += 4
    if "graduate" in text or "junior" in text or "entry level" in text: score += 2
    for kw in ["senior director", "chief", "10+ years", "9+ years", "8+ years", "7+ years"]:
        if kw in text: score -= 8
    if any(k in text for k in ADMIN_KWS): score -= 30
    return max(0, min(100, score))


def get_cv_recommendation(title: str, description: str) -> str:
    text = _text(title, description)
    if any(k in text for k in HRIS_KWS + PROJECT_KWS):
        return "CV-HRIS: Project Manager (HRIS)"
    if any(k in text for k in ANALYTICS_KWS):
        return "CV-ANALYTICS: HR / People Analytics"
    return "CV-HRIS: Project Manager (HRIS)"


def get_company_flags(company: str) -> list:
    tier = get_company_tier(company)
    flags = [tier]
    if any(x in company.lower() for x in MID_MARKET_TARGETS): flags.append("PRIMARY TARGET")
    if any(x in company.lower() for x in HIGH_TIER_TARGETS): flags.append("STRETCH TARGET")
    return flags


def get_job_triage(title: str, description: str, company: str = "") -> dict:
    score = calculate_fit_score(title, description)
    permit = classify_permit_path(title, description)
    tier = get_company_tier(company)
    cv = get_cv_recommendation(title, description)
    flags = get_company_flags(company)
    return {"fit_score": score, "permit_path": permit["path"], "permit_confidence": permit["confidence"], "permit_reason": permit["reason"], "company_tier": tier, "cv_rec": cv, "flags": flags}

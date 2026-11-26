"""Transparent scheme recommendation. Relevance points are NOT eligibility or approval chances."""
from app.expert_system.engine import NOT_ELIGIBLE, NEEDS_INFO, POTENTIALLY_ELIGIBLE


def profile_tags(profile):
    tags = set()
    if profile.get("is_student") or profile.get("occupation") == "student":
        tags.add("students")
    if profile.get("gender") == "female":
        tags.add("women")
    income = profile.get("annual_income")
    if income is not None and income <= 120000:
        tags.add("low_income")
    if profile.get("residence_type") == "rural":
        tags.add("rural")
    if profile.get("has_disability"):
        tags.add("differently_abled")
    return tags


def recommend(profile, scheme_outcomes, limit=None):
    """scheme_outcomes: list of (scheme, AssessmentOutcome). Returns ranked list of dicts."""
    tags = profile_tags(profile)
    ranked = []
    for scheme, outcome in scheme_outcomes:
        if outcome.result == NOT_ELIGIBLE:
            continue
        reasons, points = [], 0
        total = len(outcome.conditions)
        if total:
            pts = round(40 * len(outcome.satisfied) / total)
            points += pts
            reasons.append(f"{len(outcome.satisfied)} of {total} recorded conditions are satisfied (+{pts})")
        overlap = tags.intersection(scheme.tags("beneficiary_type"))
        if overlap:
            points += 15
            reasons.append("Beneficiary group matches your profile: " + ", ".join(sorted(t.replace("_", " ") for t in overlap)) + " (+15)")
        levels = scheme.tags("education_levels")
        if levels and profile.get("education_level") in levels:
            points += 10
            reasons.append("Your education level is in the scheme's target levels (+10)")
        districts = scheme.tags("districts")
        if districts and profile.get("district") in districts:
            points += 10
            reasons.append(f"The scheme covers your district, {profile.get('district')} (+10)")
        if outcome.result == POTENTIALLY_ELIGIBLE:
            reasons.append("No recorded condition is currently unmet")
        elif outcome.result == NEEDS_INFO and outcome.missing:
            reasons.append("More information needed for: " + ", ".join(c.label for c in outcome.missing))
        ranked.append({"scheme": scheme, "outcome": outcome, "points": points, "reasons": reasons})
    order = {POTENTIALLY_ELIGIBLE: 0, NEEDS_INFO: 1}
    ranked.sort(key=lambda r: (order.get(r["outcome"].result, 2), -r["points"], r["scheme"].name))
    return ranked[:limit] if limit else ranked

"""Reusable, database-independent IF-THEN rule engine.

A *rule* is a list of conditions. Every condition is a plain dict:

    {"attribute": "annual_income", "operator": "lte", "value": 120000, "label": "Family income"}

Each condition is evaluated against a profile dict and produces one of three statuses:
satisfied / not_satisfied / missing_information.  The rule outcome is derived only from those
condition results, so every explanation shown to a user is generated from real evaluation
output (never invented by an LLM):

    any condition not satisfied          -> "Not Eligible"
    else any condition missing info      -> "Needs More Information"
    else                                 -> "Potentially Eligible"

Results are preliminary assessments, never official decisions.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

POTENTIALLY_ELIGIBLE = "Potentially Eligible"
NOT_ELIGIBLE = "Not Eligible"
NEEDS_INFO = "Needs More Information"

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
MISSING = "missing_information"

DISCLAIMER = (
    "This is a preliminary assessment generated from the information you entered and the rules "
    "recorded in this system. It is not an official decision. Final eligibility is decided only "
    "by the concerned government department."
)

EDUCATION_LEVELS = [
    "below_8th", "8th", "10th", "12th", "diploma_iti", "undergraduate", "postgraduate", "doctorate",
]
EDUCATION_LABELS = {
    "below_8th": "Below 8th standard",
    "8th": "8th standard",
    "10th": "10th standard (SSLC)",
    "12th": "12th standard (HSC)",
    "diploma_iti": "Diploma / ITI",
    "undergraduate": "Undergraduate degree",
    "postgraduate": "Postgraduate degree",
    "doctorate": "Doctorate",
}
ORDINAL_SCALES = {"education_level": EDUCATION_LEVELS}

# Attributes a rule may refer to. The profile form and the admin rule builder both use this.
ATTRIBUTES = {
    "age": {"label": "Age", "type": "number"},
    "gender": {"label": "Gender", "type": "choice"},
    "district": {"label": "District", "type": "text"},
    "residence_type": {"label": "Residence (rural/urban)", "type": "choice"},
    "annual_income": {"label": "Annual family income", "type": "number"},
    "education_level": {"label": "Highest education completed", "type": "ordinal"},
    "occupation": {"label": "Occupation", "type": "choice"},
    "is_student": {"label": "Currently a student", "type": "bool"},
    "studied_govt_school": {"label": "Studied Classes 6-12 in a government school", "type": "bool"},
    "has_disability": {"label": "Person with disability", "type": "bool"},
    "pursuing_regular_course": {"label": "Pursuing a regular (not distance/open) course", "type": "bool"},
}

OPERATORS = {
    "gte": "is at least",
    "lte": "is at most",
    "gt": "is greater than",
    "lt": "is less than",
    "eq": "is",
    "neq": "is not",
    "in": "is one of",
    "not_in": "is none of",
    "between": "is between",
    "unknown": "has an official condition that is not yet verified",
}


def attribute_label(attr: str) -> str:
    return ATTRIBUTES.get(attr, {}).get("label", attr.replace("_", " ").capitalize())


def format_inr(n) -> str:
    n = int(n)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + s


def format_value(attr: str, v: Any) -> str:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return "not recorded"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (list, tuple)):
        return ", ".join(format_value(attr, x) for x in v)
    if attr == "annual_income":
        try:
            return "\u20b9" + format_inr(v)
        except (TypeError, ValueError):
            return str(v)
    if attr == "education_level":
        return EDUCATION_LABELS.get(v, str(v))
    if attr == "age":
        try:
            return f"{int(float(v))} years"
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, str):
        return v.replace("_", " ").capitalize() if v.islower() else v
    return str(v)


def describe_condition(cond: Dict[str, Any]) -> str:
    """Human-readable requirement, e.g. 'Annual family income is at most ₹1,20,000'."""
    attr, op, val = cond["attribute"], cond["operator"], cond.get("value")
    base = attribute_label(attr)
    if op == "unknown":
        return f"{base}: official condition not yet verified"
    if op == "between" and isinstance(val, (list, tuple)) and len(val) == 2:
        return f"{base} is between {format_value(attr, val[0])} and {format_value(attr, val[1])}"
    return f"{base} {OPERATORS.get(op, op)} {format_value(attr, val)}"


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _to_number(attr, v):
    scale = ORDINAL_SCALES.get(attr)
    if scale is not None:
        return scale.index(v) if v in scale else None
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
        return s
    return v


@dataclass
class ConditionResult:
    attribute: str
    label: str
    operator: str
    expected: Any
    actual: Any
    requirement: str
    status: str
    explanation: str


@dataclass
class AssessmentOutcome:
    result: str
    conditions: List[ConditionResult] = field(default_factory=list)
    summary: str = ""
    rule_version: int = 0

    @property
    def satisfied(self):
        return [c for c in self.conditions if c.status == SATISFIED]

    @property
    def not_satisfied(self):
        return [c for c in self.conditions if c.status == NOT_SATISFIED]

    @property
    def missing(self):
        return [c for c in self.conditions if c.status == MISSING]

    @property
    def attributes_considered(self):
        seen, out = set(), []
        for c in self.conditions:
            if c.attribute not in seen:
                seen.add(c.attribute)
                out.append(c)
        return out

    def to_dict(self):
        d = asdict(self)
        d["disclaimer"] = DISCLAIMER
        return d


def _compare(attr, op, actual, expected):
    """Return True/False, or None when the comparison cannot be made."""
    if op in ("gte", "lte", "gt", "lt"):
        a, e = _to_number(attr, actual), _to_number(attr, expected)
        if a is None or e is None:
            return None
        return {"gte": a >= e, "lte": a <= e, "gt": a > e, "lt": a < e}[op]
    if op == "between":
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return None
        a, lo, hi = _to_number(attr, actual), _to_number(attr, expected[0]), _to_number(attr, expected[1])
        if a is None or lo is None or hi is None:
            return None
        return lo <= a <= hi
    if op in ("eq", "neq"):
        same = _norm(actual) == _norm(expected)
        return same if op == "eq" else not same
    if op in ("in", "not_in"):
        if not isinstance(expected, (list, tuple)):
            return None
        found = _norm(actual) in [_norm(x) for x in expected]
        return found if op == "in" else not found
    return None


def evaluate_condition(cond: Dict[str, Any], profile: Dict[str, Any]) -> ConditionResult:
    attr, op, expected = cond["attribute"], cond["operator"], cond.get("value")
    label = cond.get("label") or attribute_label(attr)
    requirement = describe_condition(cond)
    actual = profile.get(attr)

    if op == "unknown":
        return ConditionResult(attr, label, op, expected, actual, requirement, MISSING,
                               f"{label}: the official condition has not been verified yet, so it cannot be checked.")
    if _is_blank(actual):
        return ConditionResult(attr, label, op, expected, None, requirement, MISSING,
                               f"{label}: more information required. Requirement: {requirement}. "
                               f"Your {attribute_label(attr).lower()} is not recorded in your profile.")

    outcome = _compare(attr, op, actual, expected)
    shown = format_value(attr, actual)
    if outcome is None:
        return ConditionResult(attr, label, op, expected, actual, requirement, MISSING,
                               f"{label}: the recorded value ({shown}) could not be compared with the rule. "
                               f"Please check your profile.")
    if outcome:
        return ConditionResult(attr, label, op, expected, actual, requirement, SATISFIED,
                               f"{label}: satisfied. Requirement: {requirement}. Recorded: {shown}.")
    return ConditionResult(attr, label, op, expected, actual, requirement, NOT_SATISFIED,
                           f"{label}: not satisfied. Requirement: {requirement}. Recorded: {shown}.")


def evaluate_rule(conditions: List[Dict[str, Any]], profile: Dict[str, Any], rule_version: int = 0) -> AssessmentOutcome:
    results = [evaluate_condition(c, profile) for c in conditions]
    out = AssessmentOutcome(result=NEEDS_INFO, conditions=results, rule_version=rule_version)

    if not results:
        out.summary = "No eligibility conditions have been recorded for this scheme yet, so eligibility cannot be assessed."
        return out
    if out.not_satisfied:
        out.result = NOT_ELIGIBLE
        names = "; ".join(c.label.lower() for c in out.not_satisfied)
        out.summary = f"Not eligible based on the currently recorded information (condition not met: {names})."
    elif out.missing:
        out.result = NEEDS_INFO
        names = "; ".join(c.label.lower() for c in out.missing)
        out.summary = f"More information is needed before this can be assessed: {names}."
    else:
        out.result = POTENTIALLY_ELIGIBLE
        out.summary = ("All recorded conditions are satisfied by your profile, so you may be eligible. "
                       "Please confirm with the official source before applying.")
    return out

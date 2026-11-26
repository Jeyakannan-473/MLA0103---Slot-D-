import hashlib
import json

from app.extensions import db
from app.expert_system.engine import evaluate_rule
from app.models import AssessmentResult, EligibilityAssessment, Scheme
from app.expert_system.engine import format_value
from app.services.scheme_service import visible_schemes_query


def profile_dict(user):
    return user.profile.as_dict() if user and user.profile else {}


def conditions_of(scheme):
    return [c.to_dict() for c in scheme.rule.conditions] if scheme.rule else []


def evaluate_scheme(profile, scheme):
    version = scheme.rule.version if scheme.rule else 0
    return evaluate_rule(conditions_of(scheme), profile, rule_version=version)


def evaluate_all(user, schemes=None):
    """In-memory evaluation of every public scheme (nothing is stored)."""
    profile = profile_dict(user)
    schemes = schemes if schemes is not None else visible_schemes_query().order_by(Scheme.name).all()
    return [(s, evaluate_scheme(profile, s)) for s in schemes]


def _signature(outcome):
    payload = {"v": outcome.rule_version,
               "c": [[c.attribute, c.operator, json.dumps(c.expected), c.status, str(c.actual)]
                     for c in outcome.conditions]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def get_or_create_assessment(user, scheme):
    """Evaluate and persist the assessment (with its rule version) unless an identical one exists."""
    outcome = evaluate_scheme(profile_dict(user), scheme)
    sig = _signature(outcome)
    latest = (EligibilityAssessment.query.filter_by(user_id=user.id, scheme_id=scheme.id)
              .order_by(EligibilityAssessment.id.desc()).first())
    if latest and latest.signature == sig:
        return latest, outcome
    record = EligibilityAssessment(user_id=user.id, scheme_id=scheme.id, rule_version=outcome.rule_version,
                                   result=outcome.result, summary=outcome.summary, signature=sig)
    for c in outcome.conditions:
        record.results.append(AssessmentResult(
            attribute=c.attribute, label=c.label, requirement=c.requirement,
            actual=format_value(c.attribute, c.actual), status=c.status, explanation=c.explanation))
    db.session.add(record)
    db.session.commit()
    return record, outcome

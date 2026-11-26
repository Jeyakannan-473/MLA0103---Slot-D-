from sqlalchemy import or_

from app.models import Scheme
from app.utils.constants import PUBLIC_STATUSES


def visible_schemes_query():
    """Schemes shown to the public: published, or awaiting verification (clearly labelled)."""
    return Scheme.query.filter(Scheme.status.in_(PUBLIC_STATUSES))


def search_schemes(q="", category_id=None, beneficiary="", district="", education=""):
    query = visible_schemes_query()
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Scheme.name.ilike(like), Scheme.description.ilike(like),
                                 Scheme.keywords.ilike(like), Scheme.department.ilike(like),
                                 Scheme.benefits.ilike(like)))
    if category_id:
        query = query.filter(Scheme.category_id == category_id)
    if beneficiary:
        query = query.filter(Scheme.beneficiary_type.ilike(f"%{beneficiary}%"))
    if district:
        query = query.filter(or_(Scheme.districts == "", Scheme.districts.is_(None),
                                 Scheme.districts.ilike(f"%{district}%")))
    if education:
        query = query.filter(or_(Scheme.education_levels == "", Scheme.education_levels.is_(None),
                                 Scheme.education_levels.ilike(f"%{education}%")))
    return query.order_by(Scheme.name)

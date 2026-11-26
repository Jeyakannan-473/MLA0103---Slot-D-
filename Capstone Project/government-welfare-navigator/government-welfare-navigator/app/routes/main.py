from flask import Blueprint, abort, render_template, request, session
from flask_login import current_user

from app.models import Scheme, SchemeCategory
from app.services.assessment_service import evaluate_scheme, profile_dict
from app.services.document_service import readiness
from app.services.scheme_service import search_schemes, visible_schemes_query
from app.expert_system.engine import EDUCATION_LABELS
from app.utils.constants import PUBLIC_STATUSES

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    featured = visible_schemes_query().order_by(Scheme.id).limit(4).all()
    categories = SchemeCategory.query.order_by(SchemeCategory.name).all()
    return render_template("index.html", featured=featured, categories=categories)


@bp.route("/schemes")
def schemes():
    q = request.args.get("q", "")[:100]
    category = request.args.get("category", type=int)
    beneficiary = request.args.get("beneficiary", "")[:30]
    district = request.args.get("district", "")[:60]
    education = request.args.get("education", "")[:30]
    page = request.args.get("page", 1, type=int)
    pagination = search_schemes(q, category, beneficiary, district, education).paginate(page=page, per_page=9, error_out=False)
    categories = SchemeCategory.query.order_by(SchemeCategory.name).all()
    return render_template("schemes/list.html", pagination=pagination, categories=categories, q=q,
                           category=category, beneficiary=beneficiary, district=district, education=education,
                           edu_labels=EDUCATION_LABELS)


@bp.route("/schemes/<slug>")
def scheme_detail(slug):
    scheme = Scheme.query.filter_by(slug=slug).first_or_404()
    is_admin = current_user.is_authenticated and current_user.is_admin
    if scheme.status not in PUBLIC_STATUSES and not is_admin:
        abort(404)
    outcome = ready = None
    if current_user.is_authenticated:
        outcome = evaluate_scheme(profile_dict(current_user), scheme)
        ready = readiness(current_user, scheme)
        recent = [i for i in session.get("recent", []) if i != scheme.id]
        session["recent"] = ([scheme.id] + recent)[:5]
    return render_template("schemes/detail.html", scheme=scheme, outcome=outcome, ready=ready)


@bp.route("/health")
def health():
    return {"status": "ok"}

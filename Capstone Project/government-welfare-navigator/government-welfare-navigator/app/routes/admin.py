from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app.expert_system.engine import ATTRIBUTES, EDUCATION_LEVELS, OPERATORS
from app.extensions import db
from app.models import (AuditLog, EligibilityAssessment, EligibilityCondition, EligibilityRule, Notification,
                        Scheme, SchemeCategory, SchemeDocument, SchemeSource, User)
from app.notifications.service import (create_notification, notify_matching_users, send_deadline_reminders,
                                       send_document_reminders)
from app.utils.audit import log_action
from app.utils.constants import (BENEFICIARY_TYPES, DISTRICTS, GENDERS, OCCUPATIONS, OPERATOR_CHOICES,
                                 RESIDENCE, SCHEME_STATUSES)
from app.utils.decorators import admin_required
from app.utils.helpers import parse_date, slugify, valid_http_url

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def guard():
    # blocks anonymous users (redirect to login) and non-admins (403) for every /admin route
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.path))
    if not current_user.is_admin:
        abort(403)


@bp.route("/")
def dashboard():
    stats = {
        "users": User.query.filter_by(role="user").count(),
        "schemes": Scheme.query.count(),
        "published": Scheme.query.filter_by(status="published").count(),
        "needs_verification": Scheme.query.filter_by(status="needs_verification").count(),
        "assessments": EligibilityAssessment.query.count(),
        "notifications": Notification.query.count(),
    }
    by_status = dict(db.session.query(Scheme.status, func.count(Scheme.id)).group_by(Scheme.status).all())
    by_cat = (db.session.query(SchemeCategory.name, func.count(Scheme.id))
              .join(Scheme, Scheme.category_id == SchemeCategory.id).group_by(SchemeCategory.name).all())
    results = dict(db.session.query(EligibilityAssessment.result, func.count(EligibilityAssessment.id))
                   .group_by(EligibilityAssessment.result).all())
    chart = {"status_labels": [l for k, l in SCHEME_STATUSES], "status_values": [by_status.get(k, 0) for k, _ in SCHEME_STATUSES],
             "cat_labels": [c[0] for c in by_cat], "cat_values": [c[1] for c in by_cat],
             "result_labels": list(results.keys()), "result_values": list(results.values())}
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", stats=stats, chart=chart, logs=logs)


# ------------------------------------------------------------------ schemes
@bp.route("/schemes")
def schemes():
    status = request.args.get("status", "")
    q = Scheme.query
    if status:
        q = q.filter_by(status=status)
    return render_template("admin/schemes.html", schemes=q.order_by(Scheme.updated_at.desc()).all(), status=status)


def _scheme_form_ctx(scheme=None):
    return {"scheme": scheme, "categories": SchemeCategory.query.order_by(SchemeCategory.name).all(),
            "beneficiary_types": BENEFICIARY_TYPES, "statuses": SCHEME_STATUSES,
            "edu_levels": EDUCATION_LEVELS, "attributes": ATTRIBUTES, "operator_choices": OPERATOR_CHOICES,
            "operators": OPERATORS}


def _apply_scheme_form(scheme, form):
    errors = []
    name = form.get("name", "").strip()
    desc = form.get("description", "").strip()
    if not 3 <= len(name) <= 200:
        errors.append("Scheme name must be 3-200 characters.")
    if len(desc) < 10:
        errors.append("Please provide a description (at least 10 characters).")
    url = form.get("application_url", "").strip()
    if url and not valid_http_url(url):
        errors.append("Application URL must start with http:// or https://")
    dates = {}
    for f in ("effective_from", "valid_until"):
        d, err = parse_date(form.get(f))
        if err:
            errors.append(f"{f.replace('_', ' ').capitalize()} {err}.")
        dates[f] = d
    cat_id = form.get("category_id", type=int)
    if cat_id and not db.session.get(SchemeCategory, cat_id):
        errors.append("Unknown category.")
    if errors:
        return errors
    scheme.name, scheme.description = name, desc
    scheme.department = form.get("department", "").strip()[:200]
    scheme.category_id = cat_id or None
    scheme.beneficiary_type = ",".join(t for t in form.getlist("beneficiary_type") if t in dict(BENEFICIARY_TYPES))
    scheme.education_levels = ",".join(t for t in form.getlist("education_levels") if t in EDUCATION_LEVELS)
    scheme.districts = ",".join(t for t in form.getlist("districts") if t in DISTRICTS)
    scheme.keywords = form.get("keywords", "").strip()[:400]
    scheme.benefits = form.get("benefits", "").strip()
    scheme.application_url = url or None
    scheme.application_steps = form.get("application_steps", "").strip()
    scheme.effective_from, scheme.valid_until = dates["effective_from"], dates["valid_until"]
    scheme.is_demo = form.get("is_demo") == "on"
    return []


def _unique_slug(name, exclude_id=None):
    base = slugify(name)[:200]
    slug, n = base, 2
    while True:
        existing = Scheme.query.filter_by(slug=slug).first()
        if not existing or existing.id == exclude_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


@bp.route("/schemes/new", methods=["GET", "POST"])
def scheme_new():
    if request.method == "POST":
        scheme = Scheme(name="", description="", status="draft")
        errors = _apply_scheme_form(scheme, request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/scheme_form.html", form=request.form, **_scheme_form_ctx(None)), 400
        scheme.slug = _unique_slug(scheme.name)
        scheme.rule = EligibilityRule(version=1)
        db.session.add(scheme)
        db.session.flush()
        log_action("scheme_create", "scheme", scheme.id, scheme.name)
        db.session.commit()
        flash("Draft scheme created. Add eligibility conditions, documents and an official source, then verify and publish.", "success")
        return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))
    return render_template("admin/scheme_form.html", form=None, **_scheme_form_ctx(None))


def _get_scheme(scheme_id):
    s = db.session.get(Scheme, scheme_id)
    if s is None:
        abort(404)
    return s


@bp.route("/schemes/<int:scheme_id>", methods=["GET", "POST"])
def scheme_edit(scheme_id):
    scheme = _get_scheme(scheme_id)
    if request.method == "POST":
        errors = _apply_scheme_form(scheme, request.form)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "danger")
            return render_template("admin/scheme_form.html", form=request.form, **_scheme_form_ctx(scheme)), 400
        scheme.slug = _unique_slug(scheme.name, scheme.id) if not scheme.slug else scheme.slug
        if scheme.status == "published":
            scheme.status = "needs_verification"   # edited details must be re-verified before being 'current'
            flash("Published scheme edited: status set to 'Needs verification'. Re-verify to publish again.", "warning")
        log_action("scheme_update", "scheme", scheme.id, scheme.name)
        db.session.commit()
        flash("Scheme details saved.", "success")
        return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))
    return render_template("admin/scheme_form.html", form=None, **_scheme_form_ctx(scheme))


@bp.route("/schemes/<int:scheme_id>/status", methods=["POST"])
def scheme_status(scheme_id):
    scheme = _get_scheme(scheme_id)
    status = request.form.get("status")
    if status not in ("draft", "needs_verification", "archived"):
        abort(400)
    scheme.status = status
    log_action("scheme_status", "scheme", scheme.id, status)
    db.session.commit()
    flash(f"Status changed to {status.replace('_', ' ')}.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/schemes/<int:scheme_id>/verify", methods=["POST"])
def scheme_verify(scheme_id):
    """Publishing requires a verification date, an official source and at least one verified condition."""
    scheme = _get_scheme(scheme_id)
    vdate, err = parse_date(request.form.get("last_verified"))
    problems = []
    if err or not vdate:
        problems.append("Enter a valid verification date.")
    if not any(s.source_type == "official" for s in scheme.sources):
        problems.append("Add at least one official source.")
    if not scheme.rule or not scheme.rule.conditions:
        problems.append("Add at least one eligibility condition.")
    elif any(c.operator == "unknown" for c in scheme.rule.conditions):
        problems.append("Replace all 'unknown / not yet verified' conditions with verified rules.")
    if not scheme.documents:
        problems.append("Record the required documents.")
    if problems:
        for p in problems:
            flash(p, "danger")
        return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))
    first_time = scheme.first_published_at is None
    scheme.last_verified, scheme.status, scheme.is_demo = vdate, "published", False
    if first_time:
        scheme.first_published_at = datetime.utcnow()
    log_action("scheme_publish", "scheme", scheme.id, scheme.name)
    db.session.commit()
    sent = notify_matching_users(scheme, "new_scheme" if first_time else "scheme_update")
    flash(f"Scheme verified and published. {sent} matching user(s) notified.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/schemes/<int:scheme_id>/delete", methods=["POST"])
def scheme_delete(scheme_id):
    scheme = _get_scheme(scheme_id)
    if scheme.status not in ("draft", "archived"):
        flash("Only draft or archived schemes can be deleted. Archive it first.", "danger")
    elif request.form.get("confirm_name", "").strip() != scheme.name:
        flash("Type the exact scheme name to confirm deletion.", "danger")
    elif EligibilityAssessment.query.filter_by(scheme_id=scheme.id).count():
        flash("This scheme has stored user assessments, so it cannot be deleted. Keep it archived instead.", "danger")
    else:
        log_action("scheme_delete", "scheme", scheme.id, scheme.name)
        db.session.delete(scheme)
        db.session.commit()
        flash("Scheme deleted.", "success")
        return redirect(url_for("admin.schemes"))
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/categories", methods=["POST"])
def category_add():
    name = request.form.get("name", "").strip()
    if not 2 <= len(name) <= 80:
        flash("Category name must be 2-80 characters.", "danger")
    elif SchemeCategory.query.filter_by(name=name).first():
        flash("That category already exists.", "warning")
    else:
        db.session.add(SchemeCategory(name=name, slug=slugify(name)))
        log_action("category_create", "category", None, name)
        db.session.commit()
        flash("Category added.", "success")
    return redirect(request.referrer or url_for("admin.schemes"))


# ------------------------------------------------------------------ rules
def parse_condition_value(attribute, operator, raw):
    """Return (value, error). Values are stored as JSON."""
    raw = (raw or "").strip()
    meta = ATTRIBUTES[attribute]
    if operator == "unknown":
        return None, None

    def one(x):
        x = x.strip()
        if meta["type"] == "number":
            return float(x) if "." in x else int(x)
        if meta["type"] == "bool":
            if x.lower() not in ("true", "false", "yes", "no"):
                raise ValueError
            return x.lower() in ("true", "yes")
        if meta["type"] == "ordinal" and x not in EDUCATION_LEVELS:
            raise ValueError
        return x.lower() if meta["type"] == "choice" else x

    try:
        if not raw:
            return None, "A value is required."
        if operator in ("in", "not_in"):
            return [one(p) for p in raw.split(",") if p.strip()], None
        if operator == "between":
            parts = [p for p in raw.split(",") if p.strip()]
            if len(parts) != 2:
                return None, "Enter two values separated by a comma, e.g. 18,25."
            return [one(p) for p in parts], None
        return one(raw), None
    except ValueError:
        hint = ", ".join(EDUCATION_LEVELS) if meta["type"] == "ordinal" else "a valid value for this attribute"
        return None, f"Invalid value for {meta['label']}: use {hint}."


def _bump_rule(scheme, why):
    scheme.rule.version += 1
    scheme.rule.updated_at = datetime.utcnow()
    log_action("rule_change", "scheme", scheme.id, f"v{scheme.rule.version}: {why}")
    if scheme.status == "published":
        scheme.status = "needs_verification"


@bp.route("/schemes/<int:scheme_id>/conditions", methods=["POST"])
def condition_add(scheme_id):
    scheme = _get_scheme(scheme_id)
    attr, op = request.form.get("attribute"), request.form.get("operator")
    if attr not in ATTRIBUTES or op not in OPERATORS:
        abort(400)
    value, err = parse_condition_value(attr, op, request.form.get("value"))
    if err:
        flash(err, "danger")
        return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))
    if scheme.rule is None:
        scheme.rule = EligibilityRule(version=1)
    cond = EligibilityCondition(attribute=attr, operator=op, label=request.form.get("label", "").strip()[:150] or None,
                                position=len(scheme.rule.conditions))
    cond.value = value
    scheme.rule.conditions.append(cond)
    _bump_rule(scheme, f"added {attr} {op}")
    db.session.commit()
    flash(f"Condition added. Rule version is now {scheme.rule.version}. Re-verify to publish.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/conditions/<int:cond_id>/edit", methods=["POST"])
def condition_edit(cond_id):
    cond = db.session.get(EligibilityCondition, cond_id) or abort(404)
    op = request.form.get("operator")
    if op not in OPERATORS:
        abort(400)
    value, err = parse_condition_value(cond.attribute, op, request.form.get("value"))
    scheme = cond.rule.scheme
    if err:
        flash(err, "danger")
        return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))
    cond.operator, cond.value = op, value
    cond.label = request.form.get("label", "").strip()[:150] or None
    _bump_rule(scheme, f"edited {cond.attribute}")
    db.session.commit()
    flash(f"Condition updated. Rule version is now {scheme.rule.version}. Re-verify to publish.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/conditions/<int:cond_id>/delete", methods=["POST"])
def condition_delete(cond_id):
    cond = db.session.get(EligibilityCondition, cond_id) or abort(404)
    scheme = cond.rule.scheme
    db.session.delete(cond)
    db.session.flush()
    _bump_rule(scheme, f"removed {cond.attribute}")
    db.session.commit()
    flash("Condition removed.", "info")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


# ------------------------------------------------------------------ documents & sources
@bp.route("/schemes/<int:scheme_id>/documents", methods=["POST"])
def document_add(scheme_id):
    scheme = _get_scheme(scheme_id)
    name = request.form.get("name", "").strip()
    key = slugify(request.form.get("doc_key", "").strip() or name).replace("-", "_")[:60]
    if not 2 <= len(name) <= 150:
        flash("Document name must be 2-150 characters.", "danger")
    elif any(d.doc_key == key for d in scheme.documents):
        flash("This document is already listed for the scheme.", "warning")
    else:
        scheme.documents.append(SchemeDocument(doc_key=key, name=name,
                                               description=request.form.get("description", "").strip()[:300],
                                               how_to_obtain=request.form.get("how_to_obtain", "").strip(),
                                               required=request.form.get("required") == "on",
                                               position=len(scheme.documents)))
        log_action("document_requirement_add", "scheme", scheme.id, name)
        db.session.commit()
        flash("Document requirement added.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
def document_delete(doc_id):
    doc = db.session.get(SchemeDocument, doc_id) or abort(404)
    sid = doc.scheme_id
    log_action("document_requirement_delete", "scheme", sid, doc.name)
    db.session.delete(doc)
    db.session.commit()
    flash("Document requirement removed.", "info")
    return redirect(url_for("admin.scheme_edit", scheme_id=sid))


@bp.route("/schemes/<int:scheme_id>/sources", methods=["POST"])
def source_add(scheme_id):
    scheme = _get_scheme(scheme_id)
    title, url = request.form.get("title", "").strip(), request.form.get("url", "").strip()
    stype = request.form.get("source_type", "official")
    if not title or not valid_http_url(url) or stype not in ("official", "reference"):
        flash("Enter a title and a valid http(s) URL.", "danger")
    else:
        scheme.sources.append(SchemeSource(title=title[:200], url=url, source_type=stype, accessed_on=datetime.utcnow().date()))
        log_action("source_add", "scheme", scheme.id, url)
        db.session.commit()
        flash("Source added.", "success")
    return redirect(url_for("admin.scheme_edit", scheme_id=scheme.id))


@bp.route("/sources/<int:source_id>/delete", methods=["POST"])
def source_delete(source_id):
    src = db.session.get(SchemeSource, source_id) or abort(404)
    sid = src.scheme_id
    db.session.delete(src)
    log_action("source_delete", "scheme", sid)
    db.session.commit()
    flash("Source removed.", "info")
    return redirect(url_for("admin.scheme_edit", scheme_id=sid))


# ------------------------------------------------------------------ users
@bp.route("/users")
def users():
    q = request.args.get("q", "").strip()[:100]
    query = User.query
    if q:
        query = query.filter((User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%")))
    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/users.html", pagination=pagination, q=q)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def user_toggle(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
    else:
        user.active = not user.active
        log_action("user_toggle", "user", user.id, "active" if user.active else "deactivated")
        db.session.commit()
        flash("User account updated.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@bp.route("/users/<int:user_id>/role", methods=["POST"])
def user_role(user_id):
    user = db.session.get(User, user_id) or abort(404)
    role = request.form.get("role")
    if role not in ("user", "admin") or user.id == current_user.id:
        flash("That role change is not allowed.", "danger")
    else:
        user.role = role
        log_action("user_role", "user", user.id, role)
        db.session.commit()
        flash("Role updated.", "success")
    return redirect(request.referrer or url_for("admin.users"))


# ------------------------------------------------------------------ notifications & logs
@bp.route("/notifications", methods=["GET", "POST"])
def notifications():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reminders":
            d, dl = send_document_reminders(), send_deadline_reminders()
            log_action("run_reminders", None, None, f"docs={d}, deadlines={dl}")
            db.session.commit()
            flash(f"Reminders generated: {d} document, {dl} deadline (duplicates are skipped automatically).", "success")
        elif action == "broadcast":
            title, text = request.form.get("title", "").strip(), request.form.get("message", "").strip()
            if not title or not text:
                flash("Title and message are required.", "danger")
            else:
                stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                n = sum(1 for u in User.query.filter_by(active=True, role="user").all()
                        if create_notification(u, "announcement", title, text, None, f"announcement:{stamp}"))
                log_action("broadcast", None, None, f"{title} ({n} users)")
                db.session.commit()
                flash(f"Announcement sent to {n} user(s).", "success")
        return redirect(url_for("admin.notifications"))
    stats = dict(db.session.query(Notification.ntype, func.count(Notification.id)).group_by(Notification.ntype).all())
    email = dict(db.session.query(Notification.email_status, func.count(Notification.id)).group_by(Notification.email_status).all())
    recent = Notification.query.order_by(Notification.created_at.desc()).limit(25).all()
    return render_template("admin/notifications.html", stats=stats, email=email, recent=recent)


@bp.route("/logs")
def logs():
    page = request.args.get("page", 1, type=int)
    action = request.args.get("action", "").strip()
    q = AuditLog.query
    if action:
        q = q.filter(AuditLog.action == action)
    pagination = q.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    actions = [a[0] for a in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    return render_template("admin/logs.html", pagination=pagination, actions=actions, action=action)

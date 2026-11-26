import os

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required

from app.ai.ocr import suggest_document_type
from app.ai.recommender import recommend
from app.expert_system.engine import (EDUCATION_LABELS, EDUCATION_LEVELS, NEEDS_INFO, NOT_ELIGIBLE,
                                      POTENTIALLY_ELIGIBLE)
from app.extensions import db
from app.models import (DocumentChecklist, Notification, Scheme, UserDocument, UserProfile)
from app.notifications.service import get_prefs
from app.services.assessment_service import (evaluate_all, get_or_create_assessment, profile_dict)
from app.services.document_service import checklist_map, readiness, set_status
from app.services.scheme_service import visible_schemes_query
from app.utils.audit import log_action
from app.utils.constants import DISTRICTS, DOC_HELD_STATUSES, GENDERS, OCCUPATIONS, PUBLIC_STATUSES, RESIDENCE
from app.utils.files import remove_upload, save_upload, user_folder
from app.utils.helpers import parse_date, parse_int, parse_tristate, today

bp = Blueprint("user", __name__)


def _profile():
    if current_user.profile is None:
        current_user.profile = UserProfile()
        db.session.commit()
    return current_user.profile


@bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    profile = _profile()
    outcomes = evaluate_all(current_user)
    counts = {POTENTIALLY_ELIGIBLE: 0, NEEDS_INFO: 0, NOT_ELIGIBLE: 0}
    for _, o in outcomes:
        counts[o.result] += 1
    ranked = recommend(profile.as_dict(), outcomes, limit=3)
    cmap = checklist_map(current_user)
    readiness_rows = []
    for scheme, o in outcomes:
        if o.result != NOT_ELIGIBLE:
            r = readiness(current_user, scheme, cmap)
            if r["percent"] is not None:
                readiness_rows.append({"scheme": scheme, "percent": r["percent"], "missing": len(r["missing"])})
    avg = round(sum(r["percent"] for r in readiness_rows) / len(readiness_rows)) if readiness_rows else None
    notes = (Notification.query.filter_by(user_id=current_user.id, is_archived=False)
             .order_by(Notification.created_at.desc()).limit(5).all())
    from flask import session
    recent_ids = session.get("recent", [])
    recent = [s for s in (db.session.get(Scheme, i) for i in recent_ids) if s and s.status in PUBLIC_STATUSES]
    chart = {"results": [counts[POTENTIALLY_ELIGIBLE], counts[NEEDS_INFO], counts[NOT_ELIGIBLE]],
             "readiness_labels": [r["scheme"].name[:32] for r in readiness_rows],
             "readiness_values": [r["percent"] for r in readiness_rows]}
    return render_template("user/dashboard.html", profile=profile, counts=counts, ranked=ranked, notes=notes,
                           readiness_rows=readiness_rows, avg_readiness=avg, recent=recent, chart=chart,
                           total=len(outcomes))


def _parse_profile(form):
    errors, data = [], {}
    dob, err = parse_date(form.get("date_of_birth"))
    if err:
        errors.append("Date of birth " + err + ".")
    elif dob and (dob > today() or (today().year - dob.year) > 110):
        errors.append("Please enter a realistic date of birth.")
        dob = None
    data["date_of_birth"] = dob
    gender = form.get("gender", "")
    data["gender"] = gender if gender in dict(GENDERS) else None
    district = form.get("district", "")
    data["district"] = district if district in DISTRICTS else None
    res = form.get("residence_type", "")
    data["residence_type"] = res if res in dict(RESIDENCE) else None
    income, err = parse_int(form.get("annual_income"), 0, 100_000_000)
    if err:
        errors.append("Annual family income " + err + ".")
    data["annual_income"] = income
    edu = form.get("education_level", "")
    data["education_level"] = edu if edu in EDUCATION_LEVELS else None
    occ = form.get("occupation", "")
    data["occupation"] = occ if occ in dict(OCCUPATIONS) else None
    for f in ("is_student", "studied_govt_school", "has_disability", "pursuing_regular_course"):
        data[f] = parse_tristate(form.get(f))
    return data, errors


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    p = _profile()
    if request.method == "POST":
        data, errors = _parse_profile(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("user/profile.html", profile=p, form=request.form, **_profile_ctx()), 400
        for k, v in data.items():
            setattr(p, k, v)
        log_action("profile_update", "user", current_user.id)
        db.session.commit()
        flash("Profile saved. Your eligibility results have been refreshed.", "success")
        return redirect(url_for("user.assessments"))
    return render_template("user/profile.html", profile=p, form=None, **_profile_ctx())


def _profile_ctx():
    return {"districts": DISTRICTS, "genders": GENDERS, "occupations": OCCUPATIONS, "residence": RESIDENCE,
            "edu_levels": [(k, EDUCATION_LABELS[k]) for k in EDUCATION_LEVELS]}


@bp.route("/assessments")
@login_required
def assessments():
    profile = _profile()
    rows = evaluate_all(current_user)
    order = {POTENTIALLY_ELIGIBLE: 0, NEEDS_INFO: 1, NOT_ELIGIBLE: 2}
    rows.sort(key=lambda r: (order[r[1].result], r[0].name))
    return render_template("user/assessments.html", rows=rows, profile=profile)


@bp.route("/assessments/<int:scheme_id>")
@login_required
def assessment_detail(scheme_id):
    scheme = db.session.get(Scheme, scheme_id)
    if not scheme or scheme.status not in PUBLIC_STATUSES:
        abort(404)
    record, outcome = get_or_create_assessment(current_user, scheme)
    return render_template("user/assessment_detail.html", scheme=scheme, outcome=outcome, record=record,
                           profile=profile_dict(current_user))


# ---------------------------------------------------------------- documents
@bp.route("/documents")
@login_required
def documents():
    cmap = checklist_map(current_user)
    uploads = {}
    for u in UserDocument.query.filter_by(user_id=current_user.id).order_by(UserDocument.uploaded_at.desc()).all():
        uploads.setdefault(u.doc_key, []).append(u)
    outcomes = evaluate_all(current_user)
    rows = []
    for scheme, o in outcomes:
        if scheme.documents:
            rows.append({"scheme": scheme, "outcome": o, "ready": readiness(current_user, scheme, cmap)})
    rows.sort(key=lambda r: (r["outcome"].result == NOT_ELIGIBLE, r["scheme"].name))
    return render_template("user/documents.html", rows=rows, uploads=uploads)


def _valid_doc_key(doc_key):
    from app.models import SchemeDocument
    return SchemeDocument.query.filter_by(doc_key=doc_key).first() is not None


@bp.route("/documents/<doc_key>/status", methods=["POST"])
@login_required
def document_status(doc_key):
    status = request.form.get("status")
    if status not in ("available", "missing") or not _valid_doc_key(doc_key):
        abort(400)
    set_status(current_user, doc_key, status)
    db.session.commit()
    flash("Document status updated (self-confirmed; not officially verified).", "success")
    return redirect(request.referrer or url_for("user.documents"))


@bp.route("/documents/<doc_key>/upload", methods=["POST"])
@login_required
def document_upload(doc_key):
    if not _valid_doc_key(doc_key):
        abort(400)
    info, error = save_upload(request.files.get("file"), current_user.id)
    if error:
        flash(error, "danger")
        return redirect(url_for("user.documents")), 302
    hint = suggest_document_type(info["path"], current_app.config["OCR_ENABLED"] and info["ext"] != "pdf")
    db.session.add(UserDocument(user_id=current_user.id, doc_key=doc_key, original_name=info["original_name"],
                                stored_name=info["stored_name"], mime_type=info["mime_type"],
                                size_bytes=info["size_bytes"], ocr_suggestion=hint))
    set_status(current_user, doc_key, "pending_verification")
    log_action("document_upload", "document", None, doc_key)
    db.session.commit()
    flash("File uploaded. Status is now 'pending verification' - it has not been verified by any official body."
          + (f" Automatic hint: {hint}" if hint else ""), "success")
    return redirect(url_for("user.documents"))


@bp.route("/documents/file/<int:doc_id>")
@login_required
def document_file(doc_id):
    doc = db.session.get(UserDocument, doc_id)
    if doc is None or (doc.user_id != current_user.id and not current_user.is_admin):
        abort(404)
    return send_from_directory(user_folder(doc.user_id), doc.stored_name, mimetype=doc.mime_type,
                               download_name=doc.original_name, as_attachment=True)


@bp.route("/documents/file/<int:doc_id>/delete", methods=["POST"])
@login_required
def document_delete(doc_id):
    doc = db.session.get(UserDocument, doc_id)
    if doc is None or doc.user_id != current_user.id:
        abort(404)
    key = doc.doc_key
    remove_upload(doc.user_id, doc.stored_name)
    db.session.delete(doc)
    db.session.flush()
    if not UserDocument.query.filter_by(user_id=current_user.id, doc_key=key).count():
        row = DocumentChecklist.query.filter_by(user_id=current_user.id, doc_key=key).first()
        if row and row.status == "pending_verification":
            row.status = "missing"
    db.session.commit()
    flash("Uploaded file deleted.", "info")
    return redirect(url_for("user.documents"))


# ---------------------------------------------------------------- notifications
@bp.route("/notifications")
@login_required
def notifications():
    view = request.args.get("view", "inbox")
    q = Notification.query.filter_by(user_id=current_user.id)
    q = q.filter_by(is_archived=True) if view == "archived" else q.filter_by(is_archived=False)
    if view == "unread":
        q = q.filter_by(is_read=False)
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Notification.created_at.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template("user/notifications.html", pagination=pagination, view=view,
                           prefs=get_prefs(current_user))


def _own_note(note_id):
    n = db.session.get(Notification, note_id)
    if n is None or n.user_id != current_user.id:
        abort(404)
    return n


@bp.route("/notifications/<int:note_id>/<action>", methods=["POST"])
@login_required
def notification_action(note_id, action):
    n = _own_note(note_id)
    if action == "read":
        n.is_read = True
    elif action == "archive":
        n.is_archived, n.is_read = True, True
    elif action == "restore":
        n.is_archived = False
    elif action == "delete":
        db.session.delete(n)
    else:
        abort(400)
    db.session.commit()
    return redirect(request.referrer or url_for("user.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("user.notifications"))


@bp.route("/notifications/preferences", methods=["POST"])
@login_required
def notification_preferences():
    prefs = get_prefs(current_user)
    for f in ("in_app_enabled", "email_enabled", "notify_new_scheme", "notify_scheme_update",
              "notify_document_reminder", "notify_deadline_reminder"):
        setattr(prefs, f, request.form.get(f) == "on")
    db.session.commit()
    flash("Notification preferences saved.", "success")
    return redirect(url_for("user.notifications"))

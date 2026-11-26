from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db, limiter
from app.models import NotificationPreference, User, UserProfile
from app.notifications.service import send_email
from app.utils.audit import log_action
from app.utils.helpers import is_safe_next, strong_password, valid_email

bp = Blueprint("auth", __name__)


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard"))
    form = {}
    if request.method == "POST":
        form = request.form
        name = form.get("full_name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        errors = []
        if not 2 <= len(name) <= 120:
            errors.append("Please enter your full name (2-120 characters).")
        if not valid_email(email):
            errors.append("Please enter a valid email address.")
        pw_err = strong_password(password)
        if pw_err:
            errors.append(pw_err)
        if password != form.get("confirm_password", ""):
            errors.append("Passwords do not match.")
        if not form.get("consent"):
            errors.append("Please accept the privacy notice to continue.")
        if not errors and User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists. Try signing in instead.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", form=form), 400
        user = User(full_name=name, email=email, role="user")
        user.set_password(password)
        user.profile = UserProfile()
        user.preferences = NotificationPreference()
        db.session.add(user)
        db.session.flush()
        log_action("register", "user", user.id, user_id=user.id)
        db.session.commit()
        login_user(user)
        session.permanent = True
        flash("Welcome! Please complete your profile so we can check scheme eligibility.", "success")
        return redirect(url_for("user.profile"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            if not user.active:
                flash("This account has been deactivated. Please contact the administrator.", "danger")
                return render_template("auth/login.html"), 403
            login_user(user)
            session.permanent = True
            user.last_login = datetime.utcnow()
            log_action("login", "user", user.id, user_id=user.id)
            db.session.commit()
            nxt = request.args.get("next")
            if is_safe_next(nxt):
                return redirect(nxt)
            return redirect(url_for("admin.dashboard" if user.is_admin else "user.dashboard"))
        flash("Invalid email or password.", "danger")
        return render_template("auth/login.html"), 401
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_action("logout", "user", current_user.id)
    db.session.commit()
    logout_user()
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first() if valid_email(email) else None
        if user and user.active:
            token = _serializer().dumps({"id": user.id, "h": user.password_hash[-12:]})
            link = url_for("auth.reset_password", token=token, _external=True)
            status = send_email(user.email, "Reset your Scheme Navigator password",
                                f"Use this link within 1 hour to set a new password:\n{link}\n\n"
                                "If you did not request this, ignore this email.")
            if status == "not_configured":
                current_app.logger.warning("SMTP not configured. Password reset link for %s: %s", user.email, link)
        flash("If an account exists for that email, a password reset link has been sent "
              "(if email is not configured, the link is printed in the server console).", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("This reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    user = db.session.get(User, data.get("id"))
    if not user or user.password_hash[-12:] != data.get("h"):
        flash("This reset link has already been used or is invalid.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password", "")
        err = strong_password(pw)
        if err or pw != request.form.get("confirm_password", ""):
            flash(err or "Passwords do not match.", "danger")
            return render_template("auth/reset.html"), 400
        user.set_password(pw)
        log_action("password_reset", "user", user.id, user_id=user.id)
        db.session.commit()
        flash("Password updated. You can now sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")

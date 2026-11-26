"""In-app + optional email notifications with de-duplication and user consent."""
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage

from flask import current_app

from app.extensions import db
from app.expert_system.engine import POTENTIALLY_ELIGIBLE, NEEDS_INFO
from app.models import Notification, NotificationPreference, Scheme, User
from app.services.assessment_service import evaluate_scheme, profile_dict
from app.services.document_service import checklist_map, readiness
from app.utils.constants import NOTIFICATION_PREF_FIELD


def send_email(to, subject, body):
    """Returns a status string. 'accepted_by_smtp_server' only means the server accepted the message;
    it is NOT a delivery confirmation."""
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        return "not_configured"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["MAIL_FROM"], to
    msg.set_content(body)
    try:
        if cfg.get("MAIL_USE_SSL"):
            server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=10)
        else:
            server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=10)
            if cfg.get("MAIL_USE_TLS"):
                server.starttls()
        with server:
            if cfg.get("MAIL_USERNAME"):
                server.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            server.send_message(msg)
        return "accepted_by_smtp_server"
    except Exception as exc:  # network/auth problems must never break the request
        current_app.logger.warning("Email send failed: %s", exc)
        return "failed"


def get_prefs(user):
    if user.preferences is None:
        user.preferences = NotificationPreference(user_id=user.id)
        db.session.add(user.preferences)
        db.session.flush()
    return user.preferences


def create_notification(user, ntype, title, message, scheme=None, dedupe_key=None):
    """Create a notification unless prefs forbid it or the dedupe key already exists. Returns it or None."""
    prefs = get_prefs(user)
    field = NOTIFICATION_PREF_FIELD.get(ntype)
    if field and not getattr(prefs, field):
        return None
    if not prefs.in_app_enabled and not prefs.email_enabled:
        return None
    if dedupe_key and Notification.query.filter_by(user_id=user.id, dedupe_key=dedupe_key).first():
        return None
    note = Notification(user_id=user.id, scheme_id=scheme.id if scheme else None, ntype=ntype,
                        title=title[:200], message=message, dedupe_key=dedupe_key, email_status="skipped",
                        is_archived=not prefs.in_app_enabled)
    if prefs.email_enabled:
        note.email_status = send_email(user.email, f"[Scheme Navigator] {title}", message)
    db.session.add(note)
    db.session.flush()
    return note


def _active_users():
    return User.query.filter_by(active=True, role="user").all()


def notify_matching_users(scheme, kind="new_scheme"):
    """Admin published/updated a scheme: notify users whose profiles are potentially eligible."""
    if scheme.status != "published":
        return 0
    version = scheme.rule.version if scheme.rule else 0
    count = 0
    for user in _active_users():
        if not user.profile or user.profile.completion() == 0:
            continue
        outcome = evaluate_scheme(profile_dict(user), scheme)
        if outcome.result != POTENTIALLY_ELIGIBLE:
            continue
        if kind == "new_scheme":
            title = f"New scheme that may match your profile: {scheme.name}"
            text = ("A newly published scheme appears to match the information in your profile. "
                    "This is a preliminary assessment - please review the conditions and the official source.")
            ntype = "new_scheme"
        else:
            title = f"Scheme updated: {scheme.name}"
            text = ("The rules or details of this scheme were updated and your profile still appears to "
                    "match. Please review the latest conditions and documents.")
            ntype = "scheme_update"
        if create_notification(user, ntype, title, text, scheme, f"{kind}:{scheme.id}:v{version}"):
            count += 1
    db.session.commit()
    return count


def send_document_reminders():
    """Weekly reminder (once per ISO week per scheme) about missing required documents."""
    year, week, _ = date.today().isocalendar()
    count = 0
    for user in _active_users():
        if not user.profile or user.profile.completion() == 0:
            continue
        cmap = checklist_map(user)
        for scheme in Scheme.query.filter_by(status="published").all():
            outcome = evaluate_scheme(profile_dict(user), scheme)
            if outcome.result not in (POTENTIALLY_ELIGIBLE, NEEDS_INFO):
                continue
            r = readiness(user, scheme, cmap)
            if not r["missing"] or r["required_total"] == 0:
                continue
            names = ", ".join(d.name for d in r["missing"])
            if create_notification(user, "document_reminder", f"Missing documents for {scheme.name}",
                                   f"Documents not yet marked as available: {names}.", scheme,
                                   f"docs:{scheme.id}:{year}-W{week}"):
                count += 1
    db.session.commit()
    return count


def send_deadline_reminders(days=7):
    today = date.today()
    limit = today + timedelta(days=days)
    count = 0
    schemes = Scheme.query.filter(Scheme.status == "published", Scheme.valid_until.isnot(None),
                                  Scheme.valid_until >= today, Scheme.valid_until <= limit).all()
    for scheme in schemes:
        for user in _active_users():
            if not user.profile or user.profile.completion() == 0:
                continue
            if evaluate_scheme(profile_dict(user), scheme).result != POTENTIALLY_ELIGIBLE:
                continue
            if create_notification(user, "deadline_reminder", f"Deadline approaching: {scheme.name}",
                                   f"The recorded deadline for this scheme is {scheme.valid_until:%d %b %Y}. "
                                   "Please confirm the date on the official source.", scheme,
                                   f"deadline:{scheme.id}:{scheme.valid_until.isoformat()}"):
                count += 1
    db.session.commit()
    return count

from flask import request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def log_action(action, entity=None, entity_id=None, detail=None, user_id=None):
    """Record an audit entry. Caller is responsible for committing."""
    uid = user_id
    if uid is None and getattr(current_user, "is_authenticated", False):
        uid = current_user.id
    ip = None
    try:
        ip = request.remote_addr
    except RuntimeError:
        pass
    db.session.add(AuditLog(user_id=uid, action=action, entity=entity, entity_id=entity_id,
                            detail=(detail or "")[:500], ip_address=ip))

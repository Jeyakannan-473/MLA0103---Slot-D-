from app.extensions import db
from app.models import DocumentChecklist
from app.utils.constants import DOC_HELD_STATUSES


def checklist_map(user):
    return {c.doc_key: c.status for c in DocumentChecklist.query.filter_by(user_id=user.id).all()}


def set_status(user, doc_key, status):
    row = DocumentChecklist.query.filter_by(user_id=user.id, doc_key=doc_key).first()
    if row is None:
        row = DocumentChecklist(user_id=user.id, doc_key=doc_key, status=status)
        db.session.add(row)
    else:
        row.status = status
    return row


def readiness(user, scheme, cmap=None):
    """Readiness % = held required documents / total required documents x 100.

    'Held' means the user confirmed they have it (available) or uploaded it (pending verification).
    Nothing here is officially verified.
    """
    cmap = cmap if cmap is not None else checklist_map(user)
    items = []
    for d in scheme.documents:
        items.append({"doc": d, "status": cmap.get(d.doc_key, "missing")})
    required = [i for i in items if i["doc"].required]
    held = [i for i in required if i["status"] in DOC_HELD_STATUSES]
    percent = round(len(held) * 100 / len(required)) if required else None
    missing = [i["doc"] for i in required if i["status"] not in DOC_HELD_STATUSES]
    return {"items": items, "percent": percent, "required_total": len(required),
            "held_total": len(held), "missing": missing}

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.ai.chatbot import answer
from app.extensions import db, limiter
from app.models import ChatConversation, ChatMessage

bp = Blueprint("chat", __name__)


@bp.route("/assistant")
@login_required
def assistant():
    return render_template("user/chat.html")


@bp.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def chat_api():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Please type a question."}), 400
    if len(message) > 500:
        return jsonify({"error": "Please keep your question under 500 characters."}), 400
    conv = None
    if data.get("conversation_id"):
        conv = db.session.get(ChatConversation, int(data["conversation_id"])) if str(data["conversation_id"]).isdigit() else None
        if conv is None or conv.user_id != current_user.id:
            return jsonify({"error": "Conversation not found."}), 404
    if conv is None:
        conv = ChatConversation(user_id=current_user.id)
        db.session.add(conv)
        db.session.flush()
    result = answer(current_user, message)
    db.session.add(ChatMessage(conversation_id=conv.id, role="user", content=message))
    db.session.add(ChatMessage(conversation_id=conv.id, role="assistant", content=result["reply"]))
    db.session.commit()
    return jsonify({"conversation_id": conv.id, **result})

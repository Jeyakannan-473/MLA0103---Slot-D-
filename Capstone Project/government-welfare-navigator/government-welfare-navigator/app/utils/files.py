"""Secure upload handling: extension + magic-byte validation, random stored names, never executed."""
import os
import uuid

from flask import current_app

SIGNATURES = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}
MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


def save_upload(file_storage, user_id):
    """Validate and store an upload. Returns (info_dict, error_message)."""
    if file_storage is None or not file_storage.filename:
        return None, "Please choose a file to upload."
    original = os.path.basename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
        return None, "Only PDF, PNG and JPG files are allowed."
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not any(head.startswith(sig) for sig in SIGNATURES[ext]):
        return None, "The file content does not match its extension."
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], str(int(user_id)))
    os.makedirs(folder, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(folder, stored)
    file_storage.save(path)
    size = os.path.getsize(path)
    if size == 0:
        os.remove(path)
        return None, "The uploaded file is empty."
    return {"original_name": original[:200], "stored_name": stored, "mime_type": MIME[ext], "size_bytes": size,
            "path": path, "ext": ext}, None


def user_folder(user_id):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], str(int(user_id)))


def remove_upload(user_id, stored_name):
    path = os.path.join(user_folder(user_id), os.path.basename(stored_name))
    if os.path.isfile(path):
        os.remove(path)

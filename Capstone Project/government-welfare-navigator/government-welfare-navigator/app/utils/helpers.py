import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "item"


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 254 and bool(EMAIL_RE.match(value))


def strong_password(value: str):
    """Return an error message, or None if the password is acceptable."""
    if len(value or "") < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        return "Password must contain at least one letter and one number."
    return None


def parse_int(value, minimum=None, maximum=None):
    """Return (int|None, error|None). Blank input gives (None, None)."""
    if value is None or str(value).strip() == "":
        return None, None
    try:
        number = int(str(value).replace(",", "").strip())
    except ValueError:
        return None, "must be a whole number"
    if minimum is not None and number < minimum:
        return None, f"must be at least {minimum}"
    if maximum is not None and number > maximum:
        return None, f"must be at most {maximum}"
    return number, None


def parse_date(value):
    if not value or not str(value).strip():
        return None, None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date(), None
    except ValueError:
        return None, "must be a valid date"


def parse_tristate(value):
    """'yes' -> True, 'no' -> False, anything else -> None (not answered)."""
    v = (value or "").strip().lower()
    return True if v == "yes" else False if v == "no" else None


def is_safe_next(target: str) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/") and not target.startswith("//")


def valid_http_url(url: str) -> bool:
    try:
        p = urlparse(url or "")
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc) and len(url) <= 500


def today() -> date:
    return date.today()

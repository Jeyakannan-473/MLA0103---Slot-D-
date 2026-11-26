"""SQLAlchemy models (normalised schema for the Welfare Scheme Navigator)."""
import json
from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.utcnow()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user", index=True)  # user | admin
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_login = db.Column(db.DateTime)

    profile = db.relationship("UserProfile", uselist=False, back_populates="user", cascade="all, delete-orphan")
    preferences = db.relationship("NotificationPreference", uselist=False, back_populates="user",
                                  cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):  # Flask-Login hook
        return bool(self.active)

    @property
    def is_admin(self):
        return self.role == "admin"


PROFILE_FIELDS = ["date_of_birth", "gender", "district", "residence_type", "annual_income",
                  "education_level", "occupation", "is_student", "studied_govt_school",
                  "has_disability", "pursuing_regular_course"]


class UserProfile(db.Model):
    __tablename__ = "user_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(20))
    district = db.Column(db.String(60))
    residence_type = db.Column(db.String(10))
    annual_income = db.Column(db.Integer)
    education_level = db.Column(db.String(30))
    occupation = db.Column(db.String(40))
    is_student = db.Column(db.Boolean)
    studied_govt_school = db.Column(db.Boolean)
    has_disability = db.Column(db.Boolean)
    pursuing_regular_course = db.Column(db.Boolean)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="profile")

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        t = date.today()
        d = self.date_of_birth
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

    def as_dict(self):
        """Attribute dict consumed by the rule engine (None = not recorded)."""
        return {
            "age": self.age, "gender": self.gender, "district": self.district,
            "residence_type": self.residence_type, "annual_income": self.annual_income,
            "education_level": self.education_level, "occupation": self.occupation,
            "is_student": self.is_student, "studied_govt_school": self.studied_govt_school,
            "has_disability": self.has_disability, "pursuing_regular_course": self.pursuing_regular_course,
        }

    def completion(self):
        filled = sum(1 for f in PROFILE_FIELDS if getattr(self, f) not in (None, ""))
        return round(filled * 100 / len(PROFILE_FIELDS))


class SchemeCategory(db.Model):
    __tablename__ = "scheme_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(90), nullable=False, unique=True)
    schemes = db.relationship("Scheme", back_populates="category")


class Scheme(db.Model):
    __tablename__ = "schemes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    slug = db.Column(db.String(220), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False)
    department = db.Column(db.String(200))
    category_id = db.Column(db.Integer, db.ForeignKey("scheme_categories.id"), index=True)
    beneficiary_type = db.Column(db.String(200), default="")      # comma separated tags
    education_levels = db.Column(db.String(200), default="")      # comma separated; blank = any
    districts = db.Column(db.String(500), default="")             # comma separated; blank = all of Tamil Nadu
    keywords = db.Column(db.String(400), default="")
    benefits = db.Column(db.Text)
    application_url = db.Column(db.String(500))
    application_steps = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    effective_from = db.Column(db.Date)
    valid_until = db.Column(db.Date)                              # application deadline / validity
    last_verified = db.Column(db.Date)
    first_published_at = db.Column(db.DateTime)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    category = db.relationship("SchemeCategory", back_populates="schemes")
    sources = db.relationship("SchemeSource", back_populates="scheme", cascade="all, delete-orphan")
    rule = db.relationship("EligibilityRule", uselist=False, back_populates="scheme", cascade="all, delete-orphan")
    documents = db.relationship("SchemeDocument", back_populates="scheme", cascade="all, delete-orphan",
                                order_by="SchemeDocument.position")

    def tags(self, field):
        return [t.strip() for t in (getattr(self, field) or "").split(",") if t.strip()]


class SchemeSource(db.Model):
    __tablename__ = "scheme_sources"
    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    source_type = db.Column(db.String(20), nullable=False, default="official")  # official | reference
    accessed_on = db.Column(db.Date)
    scheme = db.relationship("Scheme", back_populates="sources")


class EligibilityRule(db.Model):
    __tablename__ = "eligibility_rules"
    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, unique=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(300))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    scheme = db.relationship("Scheme", back_populates="rule")
    conditions = db.relationship("EligibilityCondition", back_populates="rule", cascade="all, delete-orphan",
                                 order_by="EligibilityCondition.position")


class EligibilityCondition(db.Model):
    __tablename__ = "eligibility_conditions"
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey("eligibility_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute = db.Column(db.String(50), nullable=False)
    operator = db.Column(db.String(20), nullable=False)
    value_json = db.Column(db.Text)       # JSON-encoded expected value
    label = db.Column(db.String(150))
    position = db.Column(db.Integer, default=0)
    rule = db.relationship("EligibilityRule", back_populates="conditions")

    @property
    def value(self):
        try:
            return json.loads(self.value_json) if self.value_json is not None else None
        except ValueError:
            return None

    @value.setter
    def value(self, v):
        self.value_json = json.dumps(v)

    def to_dict(self):
        return {"id": self.id, "attribute": self.attribute, "operator": self.operator,
                "value": self.value, "label": self.label}


class EligibilityAssessment(db.Model):
    __tablename__ = "eligibility_assessments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_version = db.Column(db.Integer, nullable=False)
    result = db.Column(db.String(40), nullable=False)
    summary = db.Column(db.Text)
    signature = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    scheme = db.relationship("Scheme")
    results = db.relationship("AssessmentResult", back_populates="assessment", cascade="all, delete-orphan")


class AssessmentResult(db.Model):
    __tablename__ = "assessment_results"
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("eligibility_assessments.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    attribute = db.Column(db.String(50), nullable=False)
    label = db.Column(db.String(150))
    requirement = db.Column(db.String(300))
    actual = db.Column(db.String(200))
    status = db.Column(db.String(30), nullable=False)
    explanation = db.Column(db.Text)
    assessment = db.relationship("EligibilityAssessment", back_populates="results")


class SchemeDocument(db.Model):
    __tablename__ = "scheme_documents"
    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_key = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    how_to_obtain = db.Column(db.Text)
    required = db.Column(db.Boolean, nullable=False, default=True)
    position = db.Column(db.Integer, default=0)
    scheme = db.relationship("Scheme", back_populates="documents")
    __table_args__ = (db.UniqueConstraint("scheme_id", "doc_key", name="uq_scheme_doc"),)


class DocumentChecklist(db.Model):
    """One row per user + document type, shared by every scheme that needs that document."""
    __tablename__ = "document_checklists"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_key = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="missing")  # missing|available|pending_verification
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "doc_key", name="uq_user_doc"),)


class UserDocument(db.Model):
    __tablename__ = "user_documents"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_key = db.Column(db.String(60), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)
    mime_type = db.Column(db.String(60))
    size_bytes = db.Column(db.Integer)
    ocr_suggestion = db.Column(db.String(200))   # uncertain OCR hint, user must confirm
    uploaded_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id", ondelete="SET NULL"))
    ntype = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    dedupe_key = db.Column(db.String(120))
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    email_status = db.Column(db.String(30), default="skipped")  # skipped|not_configured|accepted_by_smtp_server|failed
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    scheme = db.relationship("Scheme")
    __table_args__ = (db.UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),)


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    in_app_enabled = db.Column(db.Boolean, nullable=False, default=True)
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)  # explicit consent required
    notify_new_scheme = db.Column(db.Boolean, nullable=False, default=True)
    notify_scheme_update = db.Column(db.Boolean, nullable=False, default=True)
    notify_document_reminder = db.Column(db.Boolean, nullable=False, default=True)
    notify_deadline_reminder = db.Column(db.Boolean, nullable=False, default=True)
    user = db.relationship("User", back_populates="preferences")


class ChatConversation(db.Model):
    __tablename__ = "chatbot_conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    messages = db.relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan",
                               order_by="ChatMessage.id")


class ChatMessage(db.Model):
    __tablename__ = "chatbot_messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chatbot_conversations.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # user | assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    conversation = db.relationship("ChatConversation", back_populates="messages")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity = db.Column(db.String(40))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    user = db.relationship("User")

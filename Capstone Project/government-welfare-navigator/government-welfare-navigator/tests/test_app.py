"""Integration tests (Flask test client + in-memory SQLite)."""
import io
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from app.extensions import db
from app.models import (DocumentChecklist, EligibilityAssessment, Notification, Scheme, User, UserProfile)
from app.notifications.service import notify_matching_users, send_deadline_reminders
from app.services.assessment_service import evaluate_scheme, get_or_create_assessment
from app.services.document_service import readiness, set_status
from app.services.seed_data import seed_demo_data
from config.config import TestConfig

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

        class Cfg(TestConfig):
            UPLOAD_FOLDER = self.tmp
        self.app = create_app(Cfg)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        seed_demo_data()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def make_user(self, email="a@example.com", role="user", **profile):
        u = User(full_name="Test User", email=email, role=role)
        u.set_password("Passw0rd!")
        u.profile = UserProfile(**profile)
        db.session.add(u)
        db.session.commit()
        return u

    def login(self, client, email, password="Passw0rd!"):
        return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    def scheme(self, fragment):
        return Scheme.query.filter(Scheme.name.ilike(f"%{fragment}%")).first()


class AuthTests(Base):
    def test_register_login_logout(self):
        r = self.client.post("/register", data={"full_name": "Asha K", "email": "Asha@Example.com", "password": "Secret123",
                                                "confirm_password": "Secret123", "consent": "on"})
        self.assertEqual(r.status_code, 302)
        user = User.query.filter_by(email="asha@example.com").first()
        self.assertIsNotNone(user)
        self.assertNotIn("Secret123", user.password_hash)       # hashed, never plain text
        self.assertTrue(user.check_password("Secret123"))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertEqual(self.client.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_invalid_registration(self):
        r = self.client.post("/register", data={"full_name": "A", "email": "bad", "password": "short", "confirm_password": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.query.count(), 0)

    def test_duplicate_email_rejected(self):
        self.make_user("dup@example.com")
        r = self.client.post("/register", data={"full_name": "Another", "email": "dup@example.com", "password": "Secret123",
                                                "confirm_password": "Secret123", "consent": "on"})
        self.assertEqual(r.status_code, 400)

    def test_bad_login(self):
        self.make_user("a@example.com")
        self.assertEqual(self.login(self.client, "a@example.com", "wrong").status_code, 401)

    def test_open_redirect_blocked(self):
        self.make_user("a@example.com")
        r = self.client.post("/login?next=//evil.com", data={"email": "a@example.com", "password": "Passw0rd!"})
        self.assertNotIn("evil.com", r.headers["Location"])

    def test_deactivated_user_cannot_login(self):
        u = self.make_user("a@example.com")
        u.active = False
        db.session.commit()
        self.assertEqual(self.login(self.client, "a@example.com").status_code, 403)


class AuthorizationTests(Base):
    def test_admin_routes_protected(self):
        self.assertEqual(self.client.get("/admin/").status_code, 302)       # anonymous -> login
        self.make_user("u@example.com")
        self.login(self.client, "u@example.com")
        self.assertEqual(self.client.get("/admin/").status_code, 403)       # normal user forbidden
        self.assertEqual(self.client.get("/admin/schemes").status_code, 403)

    def test_admin_can_open_dashboard(self):
        self.make_user("admin@example.com", role="admin")
        self.login(self.client, "admin@example.com")
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_user_cannot_read_other_users_document(self):
        owner = self.make_user("owner@example.com")
        self.make_user("other@example.com")
        c1 = self.app.test_client()
        self.login(c1, "owner@example.com")
        r = c1.post("/documents/aadhaar/upload", data={"file": (io.BytesIO(PNG), "aadhaar.png")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        from app.models import UserDocument
        doc = UserDocument.query.filter_by(user_id=owner.id).first()
        self.assertIsNotNone(doc)
        self.assertEqual(c1.get(f"/documents/file/{doc.id}").status_code, 200)
        c2 = self.app.test_client()
        self.login(c2, "other@example.com")
        self.assertEqual(c2.get(f"/documents/file/{doc.id}").status_code, 404)
        self.assertEqual(c2.post(f"/documents/file/{doc.id}/delete").status_code, 404)

    def test_notifications_are_private(self):
        a, b = self.make_user("a@example.com"), self.make_user("b@example.com")
        n = Notification(user_id=a.id, ntype="announcement", title="t", message="m")
        db.session.add(n)
        db.session.commit()
        c = self.app.test_client()
        self.login(c, "b@example.com")
        self.assertEqual(c.post(f"/notifications/{n.id}/read").status_code, 404)

    def test_upload_validation(self):
        self.make_user("a@example.com")
        self.login(self.client, "a@example.com")
        self.client.post("/documents/aadhaar/upload", data={"file": (io.BytesIO(b"MZ not an image"), "evil.png")}, content_type="multipart/form-data")
        self.client.post("/documents/aadhaar/upload", data={"file": (io.BytesIO(PNG), "run.exe")}, content_type="multipart/form-data")
        from app.models import UserDocument
        self.assertEqual(UserDocument.query.count(), 0)


class SchemeTests(Base):
    def test_search_and_filters(self):
        self.assertEqual(self.client.get("/schemes?q=health").status_code, 200)
        body = self.client.get("/schemes?q=health").get_data(as_text=True)
        self.assertIn("CMCHIS", body)
        self.assertNotIn("Pudhumai Penn Scheme (Moovalur", body)
        body = self.client.get("/schemes?beneficiary=differently_abled").get_data(as_text=True)
        self.assertIn("Differently Abled", body)
        self.assertIn("No schemes match", self.client.get("/schemes?q=zzzzqqq").get_data(as_text=True))

    def test_draft_scheme_hidden(self):
        s = self.scheme("CMCHIS")
        s.status = "draft"
        db.session.commit()
        self.assertEqual(self.client.get(f"/schemes/{s.slug}").status_code, 404)

    def test_unverified_label_shown(self):
        s = self.scheme("CMCHIS")
        self.assertIn("Awaiting verification", self.client.get(f"/schemes/{s.slug}").get_data(as_text=True))


class EligibilityTests(Base):
    def test_eligible_and_ineligible(self):
        cm = self.scheme("CMCHIS")
        poor = self.make_user("p@example.com", annual_income=100000)
        rich = self.make_user("r@example.com", annual_income=500000)
        self.assertEqual(evaluate_scheme(poor.profile.as_dict(), cm).result, "Potentially Eligible")
        out = evaluate_scheme(rich.profile.as_dict(), cm)
        self.assertEqual(out.result, "Not Eligible")
        self.assertIn("not satisfied", out.not_satisfied[0].explanation)

    def test_missing_information(self):
        u = self.make_user("m@example.com")
        self.assertEqual(evaluate_scheme(u.profile.as_dict(), self.scheme("CMCHIS")).result, "Needs More Information")

    def test_unknown_condition_keeps_needs_information(self):
        u = self.make_user("d@example.com", has_disability=True, annual_income=1000)
        out = evaluate_scheme(u.profile.as_dict(), self.scheme("Differently Abled"))
        self.assertEqual(out.result, "Needs More Information")

    def test_student_scheme_gender_split(self):
        girl = self.make_user("g@example.com", gender="female", studied_govt_school=True, is_student=True, pursuing_regular_course=True)
        self.assertEqual(evaluate_scheme(girl.profile.as_dict(), self.scheme("Pudhumai Penn")).result, "Potentially Eligible")
        self.assertEqual(evaluate_scheme(girl.profile.as_dict(), self.scheme("Tamil Pudhalvan")).result, "Not Eligible")

    def test_assessment_stores_rule_version_once(self):
        u = self.make_user("a@example.com", annual_income=50000)
        s = self.scheme("CMCHIS")
        r1, _ = get_or_create_assessment(u, s)
        r2, _ = get_or_create_assessment(u, s)
        self.assertEqual(r1.id, r2.id)                       # identical result is not duplicated
        self.assertEqual(r1.rule_version, 1)
        self.assertEqual(len(r1.results), 1)
        u.profile.annual_income = 900000
        db.session.commit()
        r3, _ = get_or_create_assessment(u, s)
        self.assertNotEqual(r1.id, r3.id)
        self.assertEqual(r3.result, "Not Eligible")

    def test_assessment_page_renders_explanation(self):
        self.make_user("a@example.com", annual_income=500000)
        self.login(self.client, "a@example.com")
        s = self.scheme("CMCHIS")
        body = self.client.get(f"/assessments/{s.id}").get_data(as_text=True)
        self.assertIn("Not Eligible", body)
        self.assertIn("Rule version used", body)
        self.assertIn("not a", body.lower())  # disclaimer present


class ProfileTests(Base):
    def test_profile_save_and_validation(self):
        u = self.make_user("a@example.com")
        self.login(self.client, "a@example.com")
        r = self.client.post("/profile", data={"annual_income": "abc"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/profile", data={"date_of_birth": "2003-05-01", "gender": "female", "district": "Chennai",
                                               "annual_income": "90000", "education_level": "12th", "is_student": "yes"})
        self.assertEqual(r.status_code, 302)
        db.session.refresh(u.profile)
        self.assertEqual(u.profile.annual_income, 90000)
        self.assertIs(u.profile.is_student, True)
        self.assertGreater(u.profile.completion(), 30)


class DocumentTests(Base):
    def test_readiness_percentage(self):
        u = self.make_user("a@example.com")
        s = self.scheme("CMCHIS")      # required: aadhaar, ration_card, income_certificate (photo optional)
        self.assertEqual(readiness(u, s)["percent"], 0)
        set_status(u, "aadhaar", "available")
        db.session.commit()
        self.assertEqual(readiness(u, s)["percent"], 33)
        set_status(u, "ration_card", "available")
        set_status(u, "income_certificate", "pending_verification")
        db.session.commit()
        r = readiness(u, s)
        self.assertEqual(r["percent"], 100)
        self.assertEqual(r["missing"], [])

    def test_status_endpoint(self):
        u = self.make_user("a@example.com")
        self.login(self.client, "a@example.com")
        self.client.post("/documents/aadhaar/status", data={"status": "available"})
        self.assertEqual(DocumentChecklist.query.filter_by(user_id=u.id, doc_key="aadhaar").first().status, "available")
        self.assertEqual(self.client.post("/documents/aadhaar/status", data={"status": "verified"}).status_code, 400)
        self.assertEqual(self.client.post("/documents/nope/status", data={"status": "available"}).status_code, 400)


class NotificationTests(Base):
    def _publish(self, s):
        s.status, s.last_verified = "published", date.today()
        db.session.commit()

    def test_new_scheme_notification_and_dedupe(self):
        match = self.make_user("m@example.com", annual_income=50000)
        no_match = self.make_user("n@example.com", annual_income=900000)
        s = self.scheme("CMCHIS")
        self._publish(s)
        self.assertEqual(notify_matching_users(s, "new_scheme"), 1)
        self.assertEqual(Notification.query.filter_by(user_id=match.id).count(), 1)
        self.assertEqual(Notification.query.filter_by(user_id=no_match.id).count(), 0)
        self.assertEqual(notify_matching_users(s, "new_scheme"), 0)       # no repeats

    def test_unpublished_scheme_does_not_notify(self):
        self.make_user("m@example.com", annual_income=50000)
        self.assertEqual(notify_matching_users(self.scheme("CMCHIS"), "new_scheme"), 0)

    def test_preferences_respected(self):
        u = self.make_user("m@example.com", annual_income=50000)
        from app.notifications.service import get_prefs
        get_prefs(u).notify_new_scheme = False
        db.session.commit()
        s = self.scheme("CMCHIS")
        self._publish(s)
        self.assertEqual(notify_matching_users(s, "new_scheme"), 0)

    def test_email_not_claimed_without_smtp(self):
        u = self.make_user("m@example.com", annual_income=50000)
        from app.notifications.service import get_prefs
        get_prefs(u).email_enabled = True
        db.session.commit()
        s = self.scheme("CMCHIS")
        self._publish(s)
        notify_matching_users(s, "new_scheme")
        self.assertEqual(Notification.query.first().email_status, "not_configured")

    def test_deadline_reminder(self):
        self.make_user("m@example.com", annual_income=50000)
        s = self.scheme("CMCHIS")
        self._publish(s)
        s.valid_until = date.today() + timedelta(days=3)
        db.session.commit()
        self.assertEqual(send_deadline_reminders(), 1)
        self.assertEqual(send_deadline_reminders(), 0)

    def test_mark_read_archive_delete(self):
        u = self.make_user("a@example.com")
        n = Notification(user_id=u.id, ntype="announcement", title="t", message="m")
        db.session.add(n)
        db.session.commit()
        self.login(self.client, "a@example.com")
        self.client.post(f"/notifications/{n.id}/read")
        self.assertTrue(db.session.get(Notification, n.id).is_read)
        self.client.post(f"/notifications/{n.id}/archive")
        self.assertTrue(db.session.get(Notification, n.id).is_archived)
        self.client.post(f"/notifications/{n.id}/delete")
        self.assertIsNone(db.session.get(Notification, n.id))


class AdminTests(Base):
    def setUp(self):
        super().setUp()
        self.make_user("admin@example.com", role="admin")
        self.login(self.client, "admin@example.com")

    def test_create_scheme_and_rule_without_code_change(self):
        r = self.client.post("/admin/schemes/new", data={"name": "Test Scholarship", "description": "A test scholarship scheme for students.",
                                                          "application_url": "https://example.gov.in/apply"})
        self.assertEqual(r.status_code, 302)
        s = Scheme.query.filter_by(name="Test Scholarship").first()
        self.assertEqual(s.status, "draft")
        self.client.post(f"/admin/schemes/{s.id}/conditions", data={"attribute": "annual_income", "operator": "lte", "value": "200000", "label": "Income"})
        db.session.refresh(s)
        self.assertEqual(s.rule.version, 2)
        self.assertEqual(s.rule.conditions[0].value, 200000)
        c_id = s.rule.conditions[0].id
        self.client.post(f"/admin/conditions/{c_id}/edit", data={"operator": "lte", "value": "300000", "label": "Income"})
        db.session.refresh(s)
        self.assertEqual(s.rule.conditions[0].value, 300000)
        self.assertEqual(s.rule.version, 3)

    def test_invalid_scheme_and_condition_input(self):
        r = self.client.post("/admin/schemes/new", data={"name": "x", "description": "short"})
        self.assertEqual(r.status_code, 400)
        s = self.scheme("CMCHIS")
        v = s.rule.version
        self.client.post(f"/admin/schemes/{s.id}/conditions", data={"attribute": "annual_income", "operator": "lte", "value": "lots"})
        db.session.refresh(s)
        self.assertEqual(s.rule.version, v)
        self.assertEqual(self.client.post(f"/admin/schemes/{s.id}/conditions", data={"attribute": "evil", "operator": "lte", "value": "1"}).status_code, 400)

    def test_publish_requires_verification_and_notifies(self):
        user = self.make_user("m@example.com", gender="female", studied_govt_school=True, is_student=True, pursuing_regular_course=True)
        s = self.scheme("Pudhumai Penn")
        self.client.post(f"/admin/schemes/{s.id}/verify", data={"last_verified": ""})
        db.session.refresh(s)
        self.assertEqual(s.status, "needs_verification")
        self.client.post(f"/admin/schemes/{s.id}/verify", data={"last_verified": date.today().isoformat()})
        db.session.refresh(s)
        self.assertEqual(s.status, "published")
        self.assertEqual(Notification.query.filter_by(user_id=user.id).count(), 1)

    def test_cannot_publish_unknown_conditions(self):
        s = self.scheme("Differently Abled")
        self.client.post(f"/admin/schemes/{s.id}/verify", data={"last_verified": date.today().isoformat()})
        db.session.refresh(s)
        self.assertNotEqual(s.status, "published")

    def test_delete_safeguards(self):
        s = self.scheme("CMCHIS")
        self.client.post(f"/admin/schemes/{s.id}/delete", data={"confirm_name": s.name})
        self.assertIsNotNone(db.session.get(Scheme, s.id))                 # needs_verification: refused
        s.status = "archived"
        u = self.make_user("a@example.com", annual_income=1)
        get_or_create_assessment(u, s)
        db.session.commit()
        self.client.post(f"/admin/schemes/{s.id}/delete", data={"confirm_name": s.name})
        self.assertIsNotNone(db.session.get(Scheme, s.id))                 # has assessments: refused
        db.session.query(EligibilityAssessment).delete()
        db.session.commit()
        self.client.post(f"/admin/schemes/{s.id}/delete", data={"confirm_name": "wrong"})
        self.assertIsNotNone(db.session.get(Scheme, s.id))                 # wrong confirmation: refused
        self.client.post(f"/admin/schemes/{s.id}/delete", data={"confirm_name": s.name})
        self.assertIsNone(db.session.get(Scheme, s.id))

    def test_user_management_and_logs(self):
        u = self.make_user("a@example.com")
        self.client.post(f"/admin/users/{u.id}/toggle")
        db.session.refresh(u)
        self.assertFalse(u.active)
        self.assertEqual(self.client.get("/admin/logs").status_code, 200)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        self.assertEqual(self.client.get("/admin/notifications").status_code, 200)


class ChatbotTests(Base):
    def test_chat_uses_database(self):
        self.make_user("a@example.com", annual_income=500000)
        self.login(self.client, "a@example.com")
        r = self.client.post("/api/chat", json={"message": "What documents are required for Pudhumai Penn?"})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("Aadhaar", data["reply"])
        self.assertTrue(data["sources"])
        r = self.client.post("/api/chat", json={"message": "Why am I not eligible for CMCHIS?", "conversation_id": data["conversation_id"]})
        self.assertIn("not satisfied", r.get_json()["reply"])

    def test_chat_admits_unknown(self):
        self.make_user("a@example.com")
        self.login(self.client, "a@example.com")
        r = self.client.post("/api/chat", json={"message": "tell me about quantum gardening"})
        self.assertIn("could not find", r.get_json()["reply"])

    def test_chat_validation_and_isolation(self):
        a = self.make_user("a@example.com")
        self.make_user("b@example.com")
        c1 = self.app.test_client()
        self.login(c1, "a@example.com")
        conv = c1.post("/api/chat", json={"message": "hello"}).get_json()["conversation_id"]
        self.assertEqual(c1.post("/api/chat", json={"message": ""}).status_code, 400)
        c2 = self.app.test_client()
        self.login(c2, "b@example.com")
        self.assertEqual(c2.post("/api/chat", json={"message": "hi", "conversation_id": conv}).status_code, 404)

    def test_tamil_detection(self):
        from app.ai.chatbot import detect_language
        self.assertEqual(detect_language("எனக்கு எந்த திட்டங்கள்"), "ta")


if __name__ == "__main__":
    unittest.main()

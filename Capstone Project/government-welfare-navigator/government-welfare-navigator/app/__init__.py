import os

import click
from flask import Flask, render_template, request, jsonify
from flask_login import current_user

from config.config import Config
from .extensions import csrf, db, limiter, login_manager


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from .models import User, Notification

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .routes.main import bp as main_bp
    from .routes.auth import bp as auth_bp
    from .routes.user import bp as user_bp
    from .routes.chat import bp as chat_bp
    from .routes.admin import bp as admin_bp
    for bp in (main_bp, auth_bp, user_bp, chat_bp, admin_bp):
        app.register_blueprint(bp)

    from .expert_system import engine
    from .utils import constants as C

    @app.context_processor
    def inject_globals():
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False, is_archived=False).count()
        return {"unread_count": unread, "C": C, "engine": engine}

    app.jinja_env.globals["describe_condition"] = engine.describe_condition
    app.jinja_env.globals["format_value"] = engine.format_value
    app.jinja_env.globals["attribute_label"] = engine.attribute_label
    app.jinja_env.filters["inr"] = engine.format_inr
    app.jinja_env.filters["label"] = lambda v: str(v or "").replace("_", " ").capitalize()

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint and request.endpoint.startswith(("user.", "admin.", "auth.")):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def wants_json():
        return request.path.startswith("/api/")

    messages = {403: ("Access denied", "You do not have permission to view this page."),
                404: ("Page not found", "The page you are looking for does not exist or has moved."),
                413: ("File too large", "The uploaded file is larger than the 5 MB limit."),
                429: ("Too many requests", "You are sending requests too quickly. Please wait a minute and try again."),
                500: ("Something went wrong", "An unexpected error occurred. Please try again.")}

    def make_handler(code):
        def handler(err):
            title, text = messages[code]
            if wants_json():
                return jsonify({"error": text}), code
            if code == 500:
                db.session.rollback()
            return render_template("error.html", code=code, title=title, text=text), code
        return handler

    for code in messages:
        app.register_error_handler(code, make_handler(code))

    register_cli(app)
    return app


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all tables."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed")
    def seed():
        """Create tables, demo schemes (needs_verification) and the admin from .env."""
        from .services.seed_data import create_admin_from_config, seed_demo_data
        db.create_all()
        n = seed_demo_data()
        admin = create_admin_from_config(app)
        click.echo(f"Seeded {n} demonstration schemes (marked 'needs verification').")
        click.echo(f"Admin created: {admin.email}" if admin else
                   "No admin created (set ADMIN_EMAIL and ADMIN_PASSWORD (8+ chars) in .env, or it already exists).")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        from .models import User
        from .utils.helpers import strong_password, valid_email
        email = email.strip().lower()
        if not valid_email(email) or strong_password(password):
            raise click.ClickException("Invalid email or weak password (8+ chars, letters and numbers).")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("A user with that email already exists.")
        u = User(full_name=name, email=email, role="admin")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo("Admin created.")

    @app.cli.command("run-reminders")
    def run_reminders():
        """Generate document and deadline reminders (run daily from cron / Task Scheduler)."""
        from .notifications.service import send_deadline_reminders, send_document_reminders
        click.echo(f"Document reminders: {send_document_reminders()}, deadline reminders: {send_deadline_reminders()}")

# AI-Powered Government Welfare Scheme Navigator
**Explainable eligibility assessment · document readiness · smart notifications** (Tamil Nadu)
Capstone project – AI & Expert Systems. Flask · SQLAlchemy · MySQL (SQLite fallback) · Bootstrap 5 · Chart.js · Lucide.

> Independent academic project, not an official government website. All eligibility results are **preliminary**.

## What is implemented
| Module | Where |
|---|---|
| Rule-based expert system (IF-THEN, 3 outcomes, explanations, rule versions) | `app/expert_system/engine.py`, `app/services/assessment_service.py` |
| Configurable rules in the database (admin edits, no code change) | models `EligibilityRule`, `EligibilityCondition`; admin scheme page |
| Recommendation engine (transparent relevance points, not eligibility) | `app/ai/recommender.py` |
| Chat assistant (English + Tamil, DB-backed, optional LLM) | `app/ai/chatbot.py`, `app/routes/chat.py` |
| Document readiness (+ secure uploads, optional OCR hints) | `app/services/document_service.py`, `app/utils/files.py`, `app/ai/ocr.py` |
| Notifications (in-app, optional SMTP email, de-duplicated, preferences) | `app/notifications/service.py` |
| Auth (Flask-Login, hashed passwords, roles, reset flow, rate limits, CSRF) | `app/routes/auth.py`, `app/extensions.py` |
| Admin dashboard (schemes, rules, documents, sources, verify/publish, users, notifications, logs) | `app/routes/admin.py`, `app/templates/admin/` |
| 17 normalised tables | `app/models/__init__.py` |

## Quick start (VS Code, Windows / macOS / Linux)
```bash
python -m venv venv
venv\Scripts\activate            # Windows      (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
```
Edit `.env`: set `SECRET_KEY` (any long random string) and `ADMIN_EMAIL` / `ADMIN_PASSWORD` (8+ chars, letters and numbers).

```bash
flask --app run.py seed          # creates tables, demo schemes, and the admin from .env
python run.py                    # http://127.0.0.1:5000
```
With `DATABASE_URL` empty the app uses a local SQLite file (`instance/welfare.db`) – the fastest way to demo.

### MySQL (as specified)
1. Run `database_schema.sql` in MySQL (creates the database and user – change the password inside it first).
2. In `.env` set  
   `DATABASE_URL=mysql+pymysql://welfare_user:YOUR_PASSWORD@localhost:3306/welfare_navigator?charset=utf8mb4`
3. `flask --app run.py seed`
4. Optional: `python scripts/export_schema.py` writes the full generated MySQL DDL into `database_schema.sql`.

## Demo script for faculty
1. Register a user → complete **My profile** (e.g. female, student, government school = yes, regular course = yes, income 90000).
2. **Eligibility** page → open a scheme → see every condition, your value, rule version, sources, disclaimer.
3. Change income to 500000 → CMCHIS flips to *Not Eligible* with the reason; leave a field blank → *Needs More Information*.
4. **Documents** → mark/upload documents, watch readiness % change.
5. Sign in as the admin → **Schemes** → open *Pudhumai Penn* → check the official source → **Verify and publish** → matching users get notifications (shown in-app; emailed only if SMTP + consent).
6. Edit a condition in the admin rule table (rule version increments, scheme returns to *Needs verification*).
7. **Assistant** → try “What documents are required for Pudhumai Penn?” and a Tamil question.

## About the scheme data (important)
All four seeded schemes are **demonstration records with status “Needs verification”**. They were compiled from public
sources (Pen Kalvi / Social Welfare Dept. pages and secondary sites) and are **not** confirmed against current official
rules. Conditions that could not be established are stored as *unknown* (e.g. the income condition of the differently-abled
overview) and are never guessed. Before presenting them as current, verify each one against the official site, correct the
rules/documents in the admin panel, and press **Verify and publish** (this sets the verification date and unlocks notifications).
Benefit amounts in the seed text are marked “verify on the official portal”.

## Configuration (`.env`)
SMTP (`MAIL_*`) enables email; **“accepted by SMTP server” ≠ delivered**. `LLM_API_URL/KEY/MODEL` (any OpenAI-compatible
endpoint) lets the assistant reword answers using *only* retrieved facts; without them the built-in rule-based assistant is used.
`OCR_ENABLED=1` (needs `pytesseract`, `Pillow`, Tesseract binary) adds uncertain document-type hints for image uploads.
Run reminders daily with `flask --app run.py run-reminders` (or the admin button).

## Tests
```bash
python -m pytest -q            # or: python -m unittest discover -s tests -t .
```
`tests/test_engine.py` – rule engine (eligible, ineligible, missing, unknown, operators).  
`tests/test_app.py` – registration/login, authorization, cross-user document access, search, assessments & rule versions,
readiness %, notification generation/dedupe/preferences, admin scheme+rule management and safeguards, chatbot, invalid input.

## Security notes
Hashed passwords, CSRF on all forms, session cookie flags, role checks on every `/admin` route, login/chat/reset rate limits,
ORM parameterised queries, upload extension + magic-byte checks with random names stored outside the web root (served only to
owner/admin), secrets only via `.env`. Set `SESSION_COOKIE_SECURE=1` behind HTTPS.

## Layout
```
app/ (models, routes, services, expert_system, ai, notifications, utils, templates, static)
config/  tests/  scripts/  uploads/  run.py  requirements.txt  .env.example  database_schema.sql
```

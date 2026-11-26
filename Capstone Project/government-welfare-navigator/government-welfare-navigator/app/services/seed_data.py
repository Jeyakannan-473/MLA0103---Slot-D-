"""Demonstration seed data. ALL schemes are seeded with status 'needs_verification' and is_demo=True:
the details below come from public secondary sources and MUST be verified against the official
department sources by an administrator before being published."""
from datetime import date

from app.extensions import db
from app.models import (EligibilityCondition, EligibilityRule, Scheme, SchemeCategory, SchemeDocument,
                        SchemeSource, User)
from app.utils.helpers import slugify

DOCS = {
    "aadhaar": ("Aadhaar Card", "Identity proof", "Download e-Aadhaar or find an enrolment centre via the UIDAI website (uidai.gov.in)."),
    "income_certificate": ("Income Certificate", "Family income proof issued by the Revenue Department",
                           "Usually applied for through the Tamil Nadu e-Sevai portal / nearest e-Sevai centre. Confirm the current process on the official portal."),
    "bank_passbook": ("Bank Passbook", "First page of the savings account passbook",
                      "Copy of the first page of the passbook/statement of an Aadhaar-linked savings account in the beneficiary's name."),
    "school_study_cert": ("Government School Study Certificate", "Proof of study in Classes 6-12 in a government school",
                          "Request it from the headmaster of the school last attended (transfer/study certificate)."),
    "admission_proof": ("College Admission Proof / Fee Receipt", "Proof of current admission in a regular course",
                        "Available from the college office."),
    "ration_card": ("Family (Ration) Card", "Family identity / composition proof",
                    "Issued by the Civil Supplies Department; services are listed on the TNPDS portal."),
    "disability_certificate": ("Disability Certificate / UDID Card", "Proof of disability",
                               "Apply for the Unique Disability ID card (swavlambancard.gov.in) or contact the district differently-abled welfare office."),
    "passport_photo": ("Passport-size Photograph", "Recent photograph", "A recent passport-size photograph."),
}

SCHEMES = [
    {
        "name": "Pudhumai Penn Scheme (Moovalur Ramamirtham Ammaiyar Higher Education Assurance Scheme)",
        "category": "Education & Scholarships", "department": "Social Welfare Department, Government of Tamil Nadu",
        "beneficiary_type": "students,women", "education_levels": "undergraduate,diploma_iti",
        "keywords": "pudhumai penn, puthumai penn, girl students, higher education assurance, moovalur ramamirtham",
        "description": "Monthly financial assistance for girl students who studied in government schools and are pursuing higher education.",
        "benefits": "Rs. 1,000 per month to eligible girl students (as reported in public sources - verify on the official portal).",
        "application_url": "https://penkalvi.tn.gov.in/",
        "application_steps": "Applications are made through the student's school/college (institution login) on the official portal; students cannot apply directly.",
        "conditions": [("gender", "eq", "female", "Gender"), ("studied_govt_school", "eq", True, "Government school study (Classes 6-12)"),
                       ("is_student", "eq", True, "Currently a student"),
                       ("pursuing_regular_course", "eq", True, "Regular (not distance/open) course")],
        "documents": [("aadhaar", True), ("school_study_cert", True), ("admission_proof", True), ("bank_passbook", True)],
        "sources": [("Social Welfare Department - Pudhumai Penn", "https://tnsocialwelfare.tn.gov.in/en/specilisationswoman-welfare/pudhumai-penn", "official"),
                    ("Pen Kalvi portal", "https://penkalvi.tn.gov.in/", "official"),
                    ("myScheme.gov.in listing", "https://myscheme.gov.in/schemes/pudhumai-penn-scheme", "reference")],
    },
    {
        "name": "Tamil Pudhalvan Scheme",
        "category": "Education & Scholarships", "department": "Government of Tamil Nadu (listed under Social Welfare Department)",
        "beneficiary_type": "students", "education_levels": "undergraduate,diploma_iti",
        "keywords": "tamil pudhalvan, boys, higher education, government school boys",
        "description": "Monthly financial assistance for boys who studied in government schools and are pursuing higher education.",
        "benefits": "Monthly assistance for eligible students (amount to be verified on the official source).",
        "application_url": "https://tnsocialwelfare.tn.gov.in/",
        "application_steps": "Application process to be confirmed from the official department website.",
        "conditions": [("gender", "eq", "male", "Gender"), ("studied_govt_school", "eq", True, "Government school study (Classes 6-12)"),
                       ("is_student", "eq", True, "Currently a student"),
                       ("pursuing_regular_course", "eq", True, "Regular (not distance/open) course")],
        "documents": [("aadhaar", True), ("school_study_cert", True), ("admission_proof", True), ("bank_passbook", True)],
        "sources": [("Social Welfare Department (scheme listing)", "https://tnsocialwelfare.tn.gov.in/government-acts", "official")],
    },
    {
        "name": "Chief Minister's Comprehensive Health Insurance Scheme (CMCHIS)",
        "category": "Health", "department": "Government of Tamil Nadu - Health & Family Welfare",
        "beneficiary_type": "low_income,general", "education_levels": "",
        "keywords": "cmchis, health insurance, chief minister health insurance, hospital treatment, cashless",
        "description": "State health insurance scheme providing cashless treatment in empanelled hospitals for eligible families.",
        "benefits": "Cashless treatment up to a family annual limit in empanelled hospitals (limit to be verified on the official site).",
        "application_url": "https://www.cmchistn.com/",
        "application_steps": "Enrolment/card details to be confirmed on the official CMCHIS website.",
        "conditions": [("annual_income", "lte", 120000, "Annual family income limit")],
        "documents": [("aadhaar", True), ("ration_card", True), ("income_certificate", True), ("passport_photo", False)],
        "sources": [("CMCHIS official website", "https://www.cmchistn.com/", "official")],
    },
    {
        "name": "Welfare Schemes for Differently Abled Persons (overview)",
        "category": "Social Welfare", "department": "Department for the Welfare of Differently Abled Persons, Government of Tamil Nadu",
        "beneficiary_type": "differently_abled", "education_levels": "",
        "keywords": "differently abled, disability, udid, handicapped, maintenance allowance",
        "description": "Overview record for welfare assistance available to persons with disabilities. Individual schemes have their own conditions; add each scheme separately after verification.",
        "benefits": "Varies by scheme - to be recorded after verification.",
        "application_url": "https://www.tn.gov.in/",
        "application_steps": "Contact the District Differently Abled Welfare Officer or check the state portal.",
        "conditions": [("has_disability", "eq", True, "Person with disability"), ("annual_income", "unknown", None, "Scheme-specific income condition")],
        "documents": [("aadhaar", True), ("disability_certificate", True), ("ration_card", False), ("passport_photo", False)],
        "sources": [("Tamil Nadu Government portal", "https://www.tn.gov.in/", "official")],
    },
]


def seed_demo_data():
    """Idempotent: creates categories/schemes only when no schemes exist."""
    if Scheme.query.count() > 0:
        return 0
    cats = {}
    for item in SCHEMES:
        name = item["category"]
        if name not in cats:
            cat = SchemeCategory.query.filter_by(name=name).first() or SchemeCategory(name=name, slug=slugify(name))
            db.session.add(cat)
            cats[name] = cat
    db.session.flush()
    for item in SCHEMES:
        s = Scheme(name=item["name"], slug=slugify(item["name"])[:200], description=item["description"],
                   department=item["department"], category=cats[item["category"]],
                   beneficiary_type=item["beneficiary_type"], education_levels=item["education_levels"],
                   keywords=item["keywords"], benefits=item["benefits"], application_url=item["application_url"],
                   application_steps=item["application_steps"], status="needs_verification", is_demo=True)
        rule = EligibilityRule(version=1, notes="Seeded demonstration rule - verify against official source")
        for pos, (attr, op, val, label) in enumerate(item["conditions"]):
            c = EligibilityCondition(attribute=attr, operator=op, label=label, position=pos)
            c.value = val
            rule.conditions.append(c)
        s.rule = rule
        for pos, (key, required) in enumerate(item["documents"]):
            name, desc, how = DOCS[key]
            s.documents.append(SchemeDocument(doc_key=key, name=name, description=desc, how_to_obtain=how,
                                              required=required, position=pos))
        for title, url, stype in item["sources"]:
            s.sources.append(SchemeSource(title=title, url=url, source_type=stype, accessed_on=date.today()))
        db.session.add(s)
    db.session.commit()
    return len(SCHEMES)


def create_admin_from_config(app):
    email = (app.config.get("ADMIN_EMAIL") or "").strip().lower()
    password = app.config.get("ADMIN_PASSWORD") or ""
    if not email or len(password) < 8 or password == "change-me":
        return None
    if User.query.filter_by(email=email).first():
        return None
    admin = User(full_name=app.config.get("ADMIN_NAME") or "Administrator", email=email, role="admin")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    return admin

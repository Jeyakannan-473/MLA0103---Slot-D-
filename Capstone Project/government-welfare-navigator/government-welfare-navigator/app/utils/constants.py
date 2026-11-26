DISTRICTS = [
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri", "Dindigul", "Erode",
    "Kallakurichi", "Kancheepuram", "Kanyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai", "Ramanathapuram", "Ranipet",
    "Salem", "Sivaganga", "Tenkasi", "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
    "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur", "Vellore", "Viluppuram",
    "Virudhunagar",
]
GENDERS = [("female", "Female"), ("male", "Male"), ("transgender", "Transgender"), ("other", "Other / prefer not to say")]
RESIDENCE = [("rural", "Rural"), ("urban", "Urban")]
OCCUPATIONS = [
    ("student", "Student"), ("farmer", "Farmer / agricultural worker"), ("daily_wage", "Daily wage / informal worker"),
    ("self_employed", "Self-employed"), ("private_employee", "Private sector employee"),
    ("government_employee", "Government employee"), ("homemaker", "Homemaker"),
    ("unemployed", "Unemployed / job seeker"), ("retired", "Retired"), ("other", "Other"),
]
BENEFICIARY_TYPES = [
    ("students", "Students"), ("women", "Women"), ("low_income", "Low-income families"),
    ("rural", "Rural citizens"), ("differently_abled", "Differently abled persons"), ("general", "General citizens"),
]
SCHEME_STATUSES = [("draft", "Draft"), ("published", "Published"),
                   ("needs_verification", "Needs verification"), ("archived", "Archived")]
PUBLIC_STATUSES = ("published", "needs_verification")
DOC_HELD_STATUSES = ("available", "pending_verification")
OPERATOR_CHOICES = [
    ("gte", "at least (>=)"), ("lte", "at most (<=)"), ("gt", "greater than (>)"), ("lt", "less than (<)"),
    ("eq", "equals"), ("neq", "does not equal"), ("in", "is one of (comma separated)"),
    ("not_in", "is none of (comma separated)"), ("between", "between (min,max)"),
    ("unknown", "unknown / not yet verified"),
]
NOTIFICATION_TYPES = {
    "new_scheme": "New scheme", "scheme_update": "Scheme update", "document_reminder": "Missing documents",
    "deadline_reminder": "Deadline", "eligibility_alert": "Eligibility alert", "announcement": "Announcement",
}
# which preference switch controls which notification type
NOTIFICATION_PREF_FIELD = {
    "new_scheme": "notify_new_scheme", "eligibility_alert": "notify_new_scheme",
    "scheme_update": "notify_scheme_update", "document_reminder": "notify_document_reminder",
    "deadline_reminder": "notify_deadline_reminder",
}

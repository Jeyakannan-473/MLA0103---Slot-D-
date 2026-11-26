"""Optional OCR helper. Only runs when OCR_ENABLED=1 and pytesseract + Pillow are installed.
Results are only hints; the user must always confirm the document type."""
KEYWORDS = {
    "aadhaar": ["aadhaar", "unique identification authority", "uidai"],
    "income_certificate": ["income certificate", "annual income"],
    "bank_passbook": ["passbook", "account number", "ifsc"],
    "ration_card": ["ration card", "family card", "smart card"],
    "disability_certificate": ["disability", "udid", "differently abled"],
    "school_study_cert": ["transfer certificate", "study certificate", "bonafide"],
}


def suggest_document_type(path, enabled):
    if not enabled:
        return None
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(path)).lower()
    except Exception:
        return None
    for key, words in KEYWORDS.items():
        if any(w in text for w in words):
            return f"Possibly: {key.replace('_', ' ')} (uncertain - please confirm)"
    return "Document type could not be identified - please confirm manually"

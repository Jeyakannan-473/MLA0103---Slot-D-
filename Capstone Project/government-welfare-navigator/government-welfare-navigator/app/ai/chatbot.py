"""Welfare assistant. Answers are built ONLY from scheme records and the user's own evaluation results.

Without an API key this is a deterministic, database-backed assistant (intent keywords in English and
Tamil + scheme-name retrieval). If LLM_API_URL / LLM_API_KEY are set, the retrieved facts are passed to an
OpenAI-compatible endpoint for rewording; on any failure the deterministic reply is used.
"""
import difflib
import json
import re
import urllib.request

from flask import current_app

from app.ai.recommender import recommend
from app.expert_system.engine import NOT_ELIGIBLE
from app.services.assessment_service import evaluate_all, evaluate_scheme, profile_dict
from app.services.document_service import checklist_map, readiness
from app.models import Scheme
from app.services.scheme_service import visible_schemes_query

TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

INTENTS = {
    "documents": ["document", "documents", "required", "papers", "certificate list", "checklist", "ஆவண", "ஆவணங்கள்"],
    "why": ["why", "not eligible", "reject", "rejected", "reason", "ஏன்", "தகுதி இல்லை"],
    "eligibility": ["eligible", "eligibility", "qualify", "can i get", "தகுதி"],
    "apply": ["apply", "application", "how to", "website", "link", "விண்ணப்ப"],
    "income": ["income", "salary", "limit", "வருமான"],
    "benefits": ["benefit", "amount", "how much", "money", "assistance", "பலன்", "தொகை"],
    "obtain": ["obtain", "get certificate", "where to get", "how to get", "சான்றிதழ்", "e-sevai", "esevai"],
    "recommend": ["suitable", "recommend", "which scheme", "schemes for me", "suggest", "பரிந்துரை", "எந்த திட்ட"],
    "greeting": ["hello", "hi", "hey", "vanakkam", "வணக்கம்"],
}

T = {
    "en": {
        "ask_scheme": "Which scheme do you mean? Available schemes: {names}.",
        "no_info": "I could not find that information in the scheme database, so I cannot answer it. Please check the official source or contact the concerned department.",
        "disclaimer": "This is preliminary information from the scheme database, not an official decision.",
        "need_profile": "Please complete your profile first so I can check your eligibility.",
        "hello": "Hello! I can help with scheme suggestions, eligibility reasons, required documents, how to apply and how to obtain certificates. Ask me about a scheme by name.",
    },
    "ta": {
        "ask_scheme": "எந்த திட்டம் பற்றி கேட்கிறீர்கள்? கிடைக்கும் திட்டங்கள்: {names}.",
        "no_info": "அந்த தகவல் திட்டத் தரவுத்தளத்தில் கிடைக்கவில்லை, எனவே பதிலளிக்க இயலாது. அதிகாரப்பூர்வ மூலத்தைப் பார்க்கவும்.",
        "disclaimer": "இது திட்டத் தரவுத்தளத்தின் முன்னோட்ட தகவல் மட்டுமே; அதிகாரப்பூர்வ முடிவு அல்ல.",
        "need_profile": "தகுதியைச் சரிபார்க்க முதலில் உங்கள் சுயவிவரத்தை நிறைவு செய்யவும்.",
        "hello": "வணக்கம்! திட்டப் பரிந்துரை, தகுதி காரணங்கள், தேவையான ஆவணங்கள், விண்ணப்பிக்கும் முறை பற்றி கேளுங்கள். திட்டத்தின் பெயரைக் குறிப்பிடவும்.",
    },
}


def detect_language(text):
    return "ta" if TAMIL_RE.search(text or "") else "en"


def detect_intent(text):
    low = (text or "").lower()
    for intent in ("why", "obtain", "documents", "income", "apply", "benefits", "recommend", "eligibility"):
        if any(k in low for k in INTENTS[intent]):
            return intent
    words = set(re.findall(r"\w+", low))
    if words & {"hello", "hi", "hey", "vanakkam"} or "வணக்கம்" in low:
        return "greeting"
    return None


def find_scheme(text, schemes):
    low = (text or "").lower()
    best, best_score = None, 0.0
    for s in schemes:
        names = [s.name.lower()] + [k.strip().lower() for k in (s.keywords or "").split(",") if k.strip()]
        for n in names:
            if n and n in low:
                score = 1.0 + len(n) / 100
            else:
                words = [w for w in re.findall(r"[a-z]{4,}", n)]
                hits = sum(1 for w in words if w in low)
                score = hits / len(words) * 0.9 if words and hits else 0
                if not score:
                    for token in re.findall(r"[a-z]{5,}", low):
                        r = difflib.SequenceMatcher(None, token, n).ratio()
                        score = max(score, r if r > 0.8 else 0)
            if score > best_score:
                best, best_score = s, score
    return best if best_score >= 0.6 else None


def _sources(scheme):
    out = []
    if scheme.application_url:
        out.append({"title": "Official application / portal", "url": scheme.application_url})
    for s in scheme.sources:
        out.append({"title": s.title, "url": s.url})
    seen, uniq = set(), []
    for s in out:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)
    return uniq


def _unverified_note(scheme):
    return "\nNote: this scheme's rules are still awaiting official verification in this system." if scheme.status != "published" else ""


def answer(user, message):
    lang = detect_language(message)
    t = T[lang]
    schemes = visible_schemes_query().order_by(Scheme.name).all()
    scheme = find_scheme(message, schemes)
    intent = detect_intent(message)
    sources, lines = [], []

    if intent == "greeting" and not scheme:
        return {"reply": t["hello"], "sources": [], "language": lang, "engine": "rules"}

    if intent == "recommend" or (intent == "eligibility" and not scheme):
        profile = profile_dict(user)
        if not any(v not in (None, "") for v in profile.values()):
            return {"reply": t["need_profile"], "sources": [], "language": lang, "engine": "rules"}
        ranked = recommend(profile, evaluate_all(user, schemes), limit=4)
        if not ranked:
            lines.append("No scheme in the database currently appears suitable for the information in your profile.")
        for r in ranked:
            lines.append(f"- {r['scheme'].name}: {r['outcome'].result}. " + "; ".join(r["reasons"][:2]))
            sources += _sources(r["scheme"])[:1]
    elif scheme is None:
        # keyword retrieval from the scheme database
        words = [w for w in re.findall(r"[a-zA-Z]{4,}", message.lower()) if w not in
                 ("what", "which", "scheme", "schemes", "where", "when", "does", "need", "about", "tell")]
        hits = [s for s in schemes if any(w in f"{s.name} {s.description} {s.keywords} {s.benefits}".lower() for w in words)]
        if intent is None and not hits:
            return {"reply": t["no_info"] + "\n\n" + t["ask_scheme"].format(names=", ".join(s.name for s in schemes)),
                    "sources": [], "language": lang, "engine": "rules"}
        if not hits or intent in ("documents", "why", "apply", "income", "benefits", "obtain"):
            return {"reply": t["ask_scheme"].format(names=", ".join(s.name for s in schemes)), "sources": [],
                    "language": lang, "engine": "rules"}
        for s in hits[:3]:
            lines.append(f"- {s.name} ({s.department or 'department not recorded'}): {s.description[:180]}")
            sources += _sources(s)[:1]
    else:
        sources = _sources(scheme)
        profile = profile_dict(user)
        outcome = evaluate_scheme(profile, scheme)
        if intent in ("why", "eligibility"):
            lines.append(f"{scheme.name}: {outcome.result}.")
            lines.append(outcome.summary)
            for c in outcome.conditions:
                lines.append(f"- {c.explanation}")
        elif intent == "documents":
            r = readiness(user, scheme, checklist_map(user))
            if not scheme.documents:
                lines.append(t["no_info"])
            else:
                lines.append(f"Documents recorded for {scheme.name}:")
                for i in r["items"]:
                    tag = "required" if i["doc"].required else "optional"
                    lines.append(f"- {i['doc'].name} ({tag}) - your status: {i['status'].replace('_', ' ')}")
                if r["percent"] is not None:
                    lines.append(f"Document readiness: {r['percent']}% (based on your own confirmations, not official verification).")
        elif intent == "apply":
            if scheme.application_url:
                lines.append(f"You can apply or read official instructions here: {scheme.application_url}")
            if scheme.application_steps:
                lines.append(scheme.application_steps)
            if not lines:
                lines.append(t["no_info"])
        elif intent == "income":
            inc = [c for c in outcome.conditions if c.attribute == "annual_income"]
            if inc:
                for c in inc:
                    lines.append(f"Income condition recorded for {scheme.name}: {c.requirement}. {c.explanation}")
            else:
                lines.append(f"No income condition is recorded for {scheme.name} in this database. " + t["no_info"])
        elif intent == "benefits":
            lines.append(scheme.benefits or t["no_info"])
        elif intent == "obtain":
            found = [d for d in scheme.documents if d.how_to_obtain]
            if found:
                for d in found:
                    lines.append(f"- {d.name}: {d.how_to_obtain}")
            else:
                lines.append(t["no_info"])
        else:
            lines.append(f"{scheme.name} - {scheme.description}")
            if scheme.benefits:
                lines.append("Benefits: " + scheme.benefits)
        lines.append(_unverified_note(scheme).strip())

    reply = "\n".join(l for l in lines if l) + "\n\n" + t["disclaimer"]
    seen, uniq = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)
    engine = "rules"
    llm = _llm_rewrite(message, reply, lang)
    if llm:
        reply, engine = llm, "llm"
    return {"reply": reply, "sources": uniq[:5], "language": lang, "engine": engine}


def _llm_rewrite(question, facts, lang):
    cfg = current_app.config
    if not (cfg.get("LLM_API_URL") and cfg.get("LLM_API_KEY") and cfg.get("LLM_MODEL")):
        return None
    system = ("You explain Indian government welfare scheme information in simple words. Use ONLY the FACTS "
              "provided. Never add rules, amounts, dates or links that are not in FACTS. Do not give definitive "
              "approval or legal decisions. Reply in " + ("Tamil" if lang == "ta" else "English") + ".")
    body = json.dumps({"model": cfg["LLM_MODEL"], "temperature": 0.2, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": f"QUESTION: {question}\n\nFACTS:\n{facts}"}]}).encode()
    req = urllib.request.Request(cfg["LLM_API_URL"], data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {cfg['LLM_API_KEY']}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as exc:
        current_app.logger.warning("LLM call failed, using rule-based reply: %s", exc)
        return None

"""
Clarifying questions — asked of the user in a popup AFTER the feasibility check and BEFORE the
Business Requirements Document is generated.

Why: a BRD that ends with an "Open Questions" list hands the reader homework. Instead the system
works out what it still needs to know, asks the user once, and writes the answers into the document.
Two kinds of gap are asked about:

  * discovery questions that were skipped, left pending, or answered "Not sure" ("dq:<question id>")
    — the answer is written back onto the discovery question itself, so the scale / availability /
    security profile and every document recompute from it;
  * business parameters that would otherwise stay "TBD" in the BRD ("kp:<parameter>")
    — the answer replaces the TBD value and the row becomes "Confirmed".

Answers (and "skipped") are stored on ProjectContext.clarifications, so a project that is re-run is
never asked the same thing twice, and every agent prompt sees them as settled decisions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import ProjectContext  # noqa: E402

CONFIRMED = "Confirmed — stakeholder"
RECOMMENDED = "Recommended — confirm"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60]


def _kp_rows(context: ProjectContext) -> list[dict]:
    import content_kit as ck
    return ck.build_key_parameters(ck.select_modules(context), context)


def _recorded(context: ProjectContext) -> dict[str, dict]:
    return {c["id"]: c for c in context.clarifications}


def pending_questions(context: ProjectContext) -> list[dict]:
    """What still needs asking (empty when everything was already answered or skipped here)."""
    done = _recorded(context)
    out: list[dict] = []
    for q in context.discovery_questions:
        qid = f"dq:{q.id}"
        unsure = bool(q.answer) and "not sure" in q.answer.lower()
        if qid in done or not (q.status.value in ("pending", "skipped") or unsure):
            continue
        out.append({"id": qid, "kind": "discovery", "text": q.text, "category": q.category,
                    "hint": "You skipped this earlier." if q.status.value != "answered" else f"You answered: {q.answer}",
                    "options": list(q.options), "multi_select": q.multi_select})
    for p in _kp_rows(context):
        if str(p.get("status", "")).upper() != "TBD":
            continue
        qid = f"kp:{_slug(p['parameter'])}"
        if qid in done:
            continue
        out.append({"id": qid, "kind": "parameter", "text": f"What is your decision on: {p['parameter']}?",
                    "category": "business decision", "hint": str(p.get("value", "")), "options": [], "multi_select": False,
                    "parameter": p["parameter"]})
    return out


# ---------------------------------------------------------------------------
# AI recommendations: a best-choice suggestion for every question, reasoned from the OTHER answers
# ---------------------------------------------------------------------------

_UNSURE = re.compile(r"not (sure|decided)|haven'?t decided|don'?t know|unsure", re.I)


def _answer_map(context: ProjectContext, draft: dict | None) -> dict[str, str]:
    """Discovery answers, overlaid with whatever is currently selected in the popup (draft keyed by item id)."""
    a = {q.id: (q.answer or "") for q in context.discovery_questions if q.answer and not _UNSURE.search(q.answer)}
    for k, v in (draft or {}).items():
        if k.startswith("dq:") and v and not _UNSURE.search(v):
            a[k[3:]] = v
    return a


def _pick(options: list[str], *prefs: str) -> str | None:
    for pref in prefs:
        for o in options:
            if pref.lower() in o.lower():
                return o
    return None


def _usable(options: list[str]) -> list[str]:
    return [o for o in options if not _UNSURE.search(o) and o != "Something else"]


def _payments(a: dict, idea: str) -> bool:
    blob = " ".join(a.values()).lower() + " " + idea.lower()
    return any(w in blob for w in ("payment", "pay ", "card", "subscription", "checkout", "booking"))


def _suggest_discovery(item: dict, a: dict, idea: str) -> tuple[str | list | None, str]:
    qid, opts = item["id"][3:], _usable(item.get("options") or [])
    local = any(w in idea.lower() for w in ("local", "city", "neighbour", "neighborhood", "home ", "nearby"))
    users = a.get("nfr_users_12m", "")
    small = users.startswith(("Under", "500–5,000"))
    pays = _payments(a, idea)
    if qid == "nfr_users_12m":
        return _pick(opts, "500–5,000"), "A typical first-year range for a new product with no existing audience; revisit once you have a launch plan."
    if qid == "nfr_peak_concurrent":
        want = {"Under 500": "Under 50", "500–5,000": "50–500", "5,000–50,000": "500–5,000",
                "50,000–500,000": "500–5,000", "500,000+": "5,000+"}.get(users, "50–500")
        why = f"Sized from your expected {users} registered users — roughly 1 in 10 online at the busiest time." if users else "A typical peak for a first-year product."
        return _pick(opts, want), why
    if qid == "nfr_availability":
        if pays or users.startswith(("5,000–50,000", "50,000", "500,000")):
            return _pick(opts, "99.9%"), "People pay or book through the product, so outages cost money and trust — 99.9% is the usual baseline."
        return _pick(opts, "99%"), "No payments or large audience yet, so a few hours of downtime a month is a sensible, cheaper target."
    if qid == "nfr_data_sensitivity":
        picks = [_pick(opts, "Personal details")] + ([_pick(opts, "Payment")] if pays else [])
        return [x for x in picks if x], ("Accounts hold names and contact details" + (", and payments are taken, so card data is in scope (the processor holds it)." if pays else "."))
    if qid == "nfr_geography":
        if small and local:
            return _pick(opts, "One city"), "The idea is local and your first-year volume is small — launching in one place keeps regulation and operations simple."
        return _pick(opts, "One country"), "Starting in one country keeps legal and tax scope manageable; expand once it works."
    if qid.endswith("payment"):
        return _pick(opts, "At time of booking", "upfront", "At checkout"), "Taking payment up front secures the provider's time and cuts no-shows."
    if qid.endswith("cancellation") or qid.endswith("refund"):
        return _pick(opts, "Tiered"), "A notice-based tiered policy is fair to both sides and is the most common choice."
    if qid.endswith("providers"):
        sensitive = any(w in a.get("nfr_data_sensitivity", "") for w in ("Health", "Children", "Government"))
        return (_pick(opts, "Fully vetted") if sensitive else _pick(opts, "review step")), \
               ("You handle highly sensitive data, so providers should be fully vetted." if sensitive else "Open sign-up with a quick review balances growth against quality.")
    if qid.endswith("scheduling"):
        return _pick(opts, "set their own"), "Providers know their own availability best; this also avoids central scheduling work."
    if qid == "mock_platform":
        return _pick(opts, "Both web"), "Consumers expect a mobile experience while providers and admins usually work best on the web."
    return (opts[0] if opts else None), "The most common, lowest-risk option given your other answers."


def _suggest_parameter(item: dict, a: dict, idea: str) -> tuple[str | None, str]:
    name = item.get("parameter", "").lower()
    pays = _payments(a, idea)
    avail = a.get("nfr_availability", "")
    cancel = a.get("bp_cancellation", "")
    geo = a.get("nfr_geography", "")
    if "sla" in name:
        high = "99.9" in avail or "99.95" in avail
        return (("First response within 4 business hours; resolution within 2 business days", "Your availability target is high, so support should respond just as quickly.")
                if high else ("First response within 1 business day (24 hours)", "A realistic target for a small team in the first year."))
    if "retention" in name:
        return ("Delete personal data 30 days after account deletion; keep financial and legal records for the period the law requires",
                "Gives users a short grace period to change their mind" + (", while transaction records must be kept for tax and dispute purposes." if pays else "."))
    if "refund" in name:
        if "Strict" in cancel:
            return "No refund within 24 hours of the service; disputes accepted for 48 hours after it", "Matches the strict cancellation policy you chose."
        if "Flexible" in cancel:
            return "Full refund up to 24 hours before the service", "Matches the flexible cancellation policy you chose."
        return "Full refund 48+ hours before the service, 50% within 48–24 hours, none within 24 hours", "Follows the tiered, notice-based policy (the usual default)."
    if "fee" in name or "commission" in name:
        return "10–15% commission on completed bookings, charged to the provider", "A common range for two-sided marketplaces; it only earns revenue when a booking is completed."
    if "geography" in name or "regulation" in name:
        if "city" in geo.lower() or "country" in geo.lower() or not geo:
            return ("Launch in one country; apply its consumer-protection and data-protection law (confirm with counsel before launch)",
                    f"Based on your launch area ({geo or 'one country, assumed'}).")
        return ("Launch in several regions; apply GDPR-style privacy plus each market's consumer law (confirm with counsel)", f"Based on your launch area ({geo}).")
    return None, ""


def suggest(context: ProjectContext, items: list[dict], draft: dict | None = None, use_llm: bool = True) -> dict[str, dict]:
    """{item id: {"suggestion": str, "reason": str, "source": "ai"}} — a best choice for every item that can have one.
    Reasons cite the person's OTHER answers; `draft` is what is currently selected in the popup, so changing
    one answer changes the recommendations that depend on it. Uses the LLM when one is configured, and always
    falls back to the built-in rules (so a suggestion is never missing or off-list)."""
    a = _answer_map(context, draft)
    idea = getattr(context, "business_idea_raw", "") or ""
    out: dict[str, dict] = {}
    for it in items:
        if it["kind"] == "parameter":
            val, why = _suggest_parameter(it, a, idea)
        else:
            val, why = _suggest_discovery(it, a, idea)
            if isinstance(val, list):
                val = " | ".join(val) if val else None
        if val:
            out[it["id"]] = {"suggestion": val, "reason": why, "source": "ai"}
            if it["kind"] == "discovery" and it["id"][3:] not in a:
                a[it["id"][3:]] = val      # later recommendations build on this one, so the set stays consistent
    if use_llm:
        try:
            out = _refine_with_llm(context, items, a, idea, out)
        except Exception:
            pass          # advisory only — keep the rule-based suggestions
    return out


def _refine_with_llm(context, items, a, idea, base):
    from llm_client import get_client
    client = get_client()
    if client is None or not items:
        return base
    import chunked as ch
    lines = []
    for it in items:
        opts = it.get("options") or []
        lines.append(f'- id={it["id"]} | {it["text"]}' + (f' | options: {opts}' + (" (several may be chosen; join with ' | ')" if it.get("multi_select") else "") if opts else " | free text") +
                     f' | rule-based default: {base.get(it["id"], {}).get("suggestion", "none")}')
    prompt = (
        "You are a senior product analyst. The person building this product left the questions below open. Recommend the single best "
        "answer to each, reasoning from the product idea and their OTHER answers, so the choices are consistent with each other.\n\n"
        f"Product idea: {idea}\nDomain: {context.domain_classification}\n"
        "Their answers so far:\n" + "\n".join(f"- {k}: {v}" for k, v in a.items()) + "\n\nQuestions:\n" + "\n".join(lines) +
        '\n\nRules: when a question has options, "suggestion" MUST be copied exactly from the options. For free-text decisions give a concrete, '
        'specific value (numbers, durations), never "TBD". "reason" is ONE short sentence that cites the other answer it depends on. '
        'Respond ONLY with JSON: {"<id>": {"suggestion": "...", "reason": "..."}, ...}')
    data = ch.call_json(client, prompt, max_tokens=2500)
    merged = dict(base)
    for it in items:
        d = data.get(it["id"])
        if not isinstance(d, dict) or not str(d.get("suggestion", "")).strip():
            continue
        sug = str(d["suggestion"]).strip()
        opts = it.get("options") or []
        if opts:
            parts = [x.strip() for x in sug.split("|")]
            if not all(p in opts for p in parts) or (len(parts) > 1 and not it.get("multi_select")):
                continue
        merged[it["id"]] = {"suggestion": sug, "reason": str(d.get("reason", "")).strip() or base.get(it["id"], {}).get("reason", ""), "source": "ai"}
    return merged


def apply_answers(context: ProjectContext, answers: list[dict], ai_fill: bool = True) -> dict:
    """Stores the user's answers. Anything left empty is filled with the AI's recommendation (recorded as
    source "ai" so the BRD says it still needs confirming); only an item with no possible recommendation is skipped."""
    pending = {p["id"]: p for p in pending_questions(context)}
    given = {a.get("id"): str(a.get("answer") or "").strip() for a in answers or [] if a.get("id") in pending}
    draft = {k: v for k, v in given.items() if v}
    recs = suggest(context, [pending[k] for k in given if not given[k]], draft) if ai_fill else {}
    user = ai = skipped = 0
    for k, text in given.items():
        p = pending[k]
        source, reason = "user", ""
        if not text and k in recs:
            text, source, reason = recs[k]["suggestion"], "ai", recs[k]["reason"]
        rec = {"id": k, "kind": p["kind"], "text": p["text"], "answer": text, "source": source, "reason": reason,
               "status": "answered" if text else "skipped"}
        if p["kind"] == "parameter":
            rec["parameter"] = p["parameter"]
        if text and p["kind"] == "discovery":
            context.add_answer(k[3:], text)           # same path as the questionnaire
            context.system_profile = None             # scale/security profile is rebuilt from the new answer
        context.clarifications.append(rec)
        user += bool(text) and source == "user"
        ai += bool(text) and source == "ai"
        skipped += not text
    seed_locked_decisions(context)
    return {"answered": user, "ai_chosen": ai, "skipped": skipped}


def decision_lines(context: ProjectContext) -> list[str]:
    out = []
    for c in context.clarifications:
        if c.get("status") != "answered":
            continue
        who = "Stakeholder confirmed" if c.get("source", "user") == "user" else "AI-recommended, awaiting stakeholder confirmation"
        out.append(f"{who} — {c['text'].rstrip('?')}: {c['answer']}")
    return out


def seed_locked_decisions(context: ProjectContext) -> None:
    """Every agent prompt carries locked decisions, so the answers are treated as settled facts."""
    for line in decision_lines(context):
        if line not in context.locked_decisions:
            context.locked_decisions.append(line)


def apply_to_key_parameters(context: ProjectContext, params: list[dict]) -> list[dict]:
    """Writes answers into the BRD's key-parameter table: a TBD row becomes Confirmed (you decided) or
    Recommended — confirm (the AI chose it for you)."""
    by_param = {c.get("parameter"): c for c in context.clarifications if c.get("kind") == "parameter" and c.get("answer")}
    out = []
    for p in params or []:
        c = by_param.get(p.get("parameter"))
        if not c:
            out.append(p)
        else:
            out.append({**p, "value": c["answer"], "status": CONFIRMED if c.get("source", "user") == "user" else RECOMMENDED})
    return out


def brd_assumption_lines(context: ProjectContext) -> list[str]:
    """What the BRD says instead of an Open Questions list: what the stakeholder confirmed, and what the AI
    recommended on their behalf (with its reason) — each clearly labelled so nothing passes as a confirmed fact."""
    lines = []
    for c in context.clarifications:
        subject = c["text"].rstrip("?")
        if c.get("status") != "answered":
            lines.append(f"**Not confirmed (planning default used):** {subject}. The documents use a stated, "
                         "conservative default for this; revisit it when the decision is made.")
        elif c.get("source", "user") == "ai":
            lines.append(f"**Recommended by AI — please confirm:** {subject} — {c['answer']}." + (f" *Why: {c['reason']}*" if c.get("reason") else ""))
        elif c.get("kind") != "parameter":     # confirmed parameters already appear, as "Confirmed", in the key-parameters table
            lines.append(f"**Confirmed with the stakeholder before drafting:** {subject} — {c['answer']}.")
    return lines

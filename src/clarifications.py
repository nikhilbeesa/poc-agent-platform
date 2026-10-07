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


def apply_answers(context: ProjectContext, answers: list[dict]) -> dict:
    """Stores the user's answers. An empty answer means \"skip — use the planning default\"."""
    pending = {p["id"]: p for p in pending_questions(context)}
    answered = skipped = 0
    for a in answers or []:
        p = pending.get(a.get("id"))
        if not p:
            continue
        text = str(a.get("answer") or "").strip()
        rec = {"id": p["id"], "kind": p["kind"], "text": p["text"], "answer": text,
               "status": "answered" if text else "skipped"}
        if p["kind"] == "parameter":
            rec["parameter"] = p["parameter"]
        if text and p["kind"] == "discovery":
            context.add_answer(p["id"][3:], text)     # same path as the questionnaire
            context.system_profile = None             # scale/security profile is rebuilt from the new answer
        context.clarifications.append(rec)
        answered += bool(text)
        skipped += not text
    seed_locked_decisions(context)
    return {"answered": answered, "skipped": skipped}


def decision_lines(context: ProjectContext) -> list[str]:
    return [f"Stakeholder confirmed — {c['text'].rstrip('?')}: {c['answer']}"
            for c in context.clarifications if c.get("status") == "answered"]


def seed_locked_decisions(context: ProjectContext) -> None:
    """Every agent prompt carries locked decisions, so the answers are treated as settled facts."""
    for line in decision_lines(context):
        if line not in context.locked_decisions:
            context.locked_decisions.append(line)


def apply_to_key_parameters(context: ProjectContext, params: list[dict]) -> list[dict]:
    """Writes confirmed answers into the BRD's key-parameter table (a TBD row becomes Confirmed)."""
    by_param = {c.get("parameter"): c for c in context.clarifications if c.get("kind") == "parameter" and c.get("answer")}
    out = []
    for p in params or []:
        c = by_param.get(p.get("parameter"))
        out.append({**p, "value": c["answer"], "status": CONFIRMED} if c else p)
    return out


def brd_assumption_lines(context: ProjectContext) -> list[str]:
    """What the BRD says instead of an Open Questions list: confirmed answers, and — for anything the
    user chose not to answer — the planning default that is being used."""
    lines = []
    for c in context.clarifications:
        subject = c["text"].rstrip("?")
        if c.get("status") == "answered":
            if c.get("kind") == "parameter":
                continue        # already shown, as "Confirmed", in the key-parameters table
            lines.append(f"**Confirmed with the stakeholder before drafting:** {subject} — {c['answer']}.")
        else:
            lines.append(f"**Not confirmed (planning default used):** {subject}. The documents use a stated, "
                         "conservative default for this; revisit it when the decision is made.")
    return lines

"""
Rethink & resolve — what happens after a RETHINK (or any serious) feasibility verdict.

The old gate only offered the discovery answers that had NOT been looked at yet. Once a person had been through one
round, the remaining flaws (usually plan-level contradictions — "solo freelancers" vs "crew management", "offline
business" vs "software subscription") had nothing left to edit, so the run just carried on with a log line.

Now every critical/major flaw can be dealt with explicitly, each one in one of two ways:

  FIX     change the answer(s) behind it — the AI proposes a concrete answer for each, reasoned from the flaw's own
          recommended change (and, with an AI key, from the rest of the plan);
  ACCEPT  keep the plan and knowingly accept the risk. The acceptance is recorded, shown in the BRD risk register as
          "accepted by the stakeholder", and the same flaw is not raised as a blocker again unless the answers behind
          it change.

Nothing loops: a flaw is either fixed, or accepted, or still waiting for a decision.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import AgentRole, ProjectContext  # noqa: E402

SERIOUS = ("Critical", "Major")
_UNSURE = re.compile(r"not (sure|decided)|haven'?t decided|don'?t know|unsure", re.I)
_STOP = {"the", "and", "for", "that", "with", "this", "your", "from", "into", "than", "are", "not", "but", "only", "will",
         "should", "would", "could", "instead", "rather", "make", "have", "more", "less", "also", "their", "them", "what"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 2 and w not in _STOP}


def _flaws(context: ProjectContext) -> list[dict]:
    c = context.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    return [f for f in ((c.output if c else {}).get("flaws") or []) if f.get("severity") in SERIOUS]


def flaw_key(f: dict) -> str:
    """Stable across re-runs (flaw ids are renumbered each time): the answers it hangs on, else its wording."""
    ids = sorted(f.get("related_question_ids") or [])
    return ("q:" + "+".join(ids)) if ids else ("t:" + _slug(f.get("flaw", ""))[:60])


def _sig(context: ProjectContext, f: dict) -> str:
    ans = {q.id: (q.answer or "") for q in context.discovery_questions}
    return "|".join(f"{i}={ans.get(i, '')}" for i in sorted(f.get("related_question_ids") or []))


def is_accepted(context: ProjectContext, f: dict) -> bool:
    """Accepted AND nothing behind it has changed since (a changed answer re-opens the question)."""
    k, sig = flaw_key(f), _sig(context, f)
    return any(a["key"] == k and a.get("sig") == sig for a in context.accepted_flaws)


def counts(context: ProjectContext) -> dict:
    fl = _flaws(context)
    acc = sum(1 for f in fl if is_accepted(context, f))
    return {"serious": len(fl), "accepted": acc, "open": len(fl) - acc}


# ---------------------------------------------------------------------------
# Suggested fixes
# ---------------------------------------------------------------------------
def _rule_fix(f: dict, q, note: dict) -> tuple[str | None, str]:
    """Pick the option that best matches the flaw's recommended change (plain word overlap). Returns (answer, reason)."""
    change = (note or {}).get("change") or f.get("recommended_change") or ""
    target = _words(change) | _words((note or {}).get("why", ""))
    cur = {p.strip().lower() for p in str(q.answer or "").split(" | ")}
    opts = [o for o in (q.options or []) if o != "Something else" and not _UNSURE.search(o)]
    scored = sorted(((len(_words(o) & target), o) for o in opts if o.lower() not in cur), key=lambda t: -t[0])
    if not scored or scored[0][0] == 0:
        return None, ""
    best = scored[0][1]
    if q.multi_select:
        keep = [p.strip() for p in str(q.answer or "").split(" | ") if p.strip() and p.strip() in opts]
        best = " | ".join(dict.fromkeys(keep + [best]))
    return best, f"Matches the recommended change: “{change[:140]}”"


def _ways_forward(f: dict) -> list[str]:
    parts = [p.strip(" .") for p in re.split(r";|\n|(?<=\.)\s+(?=[A-Z])", str(f.get("recommended_change", ""))) if len(p.strip()) > 12]
    return parts[:3]


def plan(context: ProjectContext, use_llm: bool = True) -> list[dict]:
    """Every critical/major flaw with the answers behind it, a concrete proposed answer for each, and its state."""
    qmap = {q.id: q for q in context.discovery_questions}
    out = []
    for f in _flaws(context):
        item = {"key": flaw_key(f), "id": f.get("id", ""), "severity": f.get("severity"), "flaw": f.get("flaw", ""),
                "why": f.get("why_it_matters", ""), "recommended": f.get("recommended_change", ""),
                "ways_forward": _ways_forward(f), "accepted": is_accepted(context, f), "questions": []}
        for qid in f.get("related_question_ids") or []:
            q = qmap.get(qid)
            if not q:
                continue
            note = (f.get("question_notes") or {}).get(qid) or {}
            sug, why = _rule_fix(f, q, note)
            if not sug and (not q.answer or _UNSURE.search(q.answer)):
                # an answer left open / "not sure" is itself the problem: propose the best-fit answer given everything else
                import clarifications as clar
                got = clar.suggest(context, [{"id": f"dq:{qid}", "kind": "discovery", "text": q.text, "options": list(q.options),
                                              "multi_select": q.multi_select}], use_llm=False).get(f"dq:{qid}")
                if got and got["suggestion"] != (q.answer or ""):
                    sug, why = got["suggestion"], got["reason"]
            item["questions"].append({"id": qid, "text": q.text, "options": list(q.options), "multi_select": q.multi_select,
                                      "current": q.answer or "", "suggestion": sug, "reason": why or note.get("why", "")})
        out.append(item)
    if use_llm and out:
        try:
            _refine_with_llm(context, out)
        except Exception:
            pass          # advisory — the rule-based proposals stand
    out.sort(key=lambda i: (i["accepted"], 0 if i["severity"] == "Critical" else 1))
    return out


def _refine_with_llm(context: ProjectContext, items: list[dict]) -> None:
    from llm_client import get_client
    client = get_client()
    if client is None:
        return
    import chunked as ch
    answers = "\n".join(f"- {q.id}: {q.answer}" for q in context.discovery_questions if q.answer)
    blocks = []
    for it in items:
        qs = "; ".join(f'{q["id"]} ("{q["text"]}", current: "{q["current"]}", options: {q["options"] or "free text"}' +
                       (", several may be chosen joined with ' | '" if q["multi_select"] else "") + ")" for q in it["questions"])
        blocks.append(f'* {it["key"]} [{it["severity"]}] {it["flaw"]}\n  recommended change: {it["recommended"]}\n  answers behind it: {qs or "none — plan-level problem"}')
    prompt = (
        "You are a senior product strategist helping a founder resolve problems found in their idea. For each problem, propose the "
        "concrete answer change that best resolves it, keeping every proposal consistent with the others and with the idea.\n\n"
        f"Idea: {context.business_idea_raw}\nAll their answers:\n{answers}\n\nProblems:\n" + "\n".join(blocks) +
        '\n\nRules: when a question has options, "answer" MUST be copied exactly from them; omit a question if its current answer is already right. '
        '"reason" is ONE short sentence. "ways_forward" = up to 3 short, distinct strategic directions (e.g. narrow the audience / change the model / '
        'keep both and phase them) — most useful for plan-level problems with no answer to change.\n'
        'Respond ONLY with JSON: {"<problem key>": {"ways_forward": ["..."], "answers": {"<question id>": {"answer": "...", "reason": "..."}}}}')
    data = ch.call_json(client, prompt, max_tokens=3000)
    for it in items:
        d = data.get(it["key"])
        if not isinstance(d, dict):
            continue
        wf = [str(x).strip() for x in (d.get("ways_forward") or []) if str(x).strip()][:3]
        if wf:
            it["ways_forward"] = wf
        for q in it["questions"]:
            a = (d.get("answers") or {}).get(q["id"])
            if not isinstance(a, dict) or not str(a.get("answer", "")).strip():
                continue
            ans = str(a["answer"]).strip()
            if q["options"] and not all(p.strip() in q["options"] for p in ans.split("|")):
                continue
            if ans != q["current"]:
                q["suggestion"], q["reason"] = ans, str(a.get("reason", "")).strip() or q["reason"]


# ---------------------------------------------------------------------------
# Applying decisions
# ---------------------------------------------------------------------------
def apply(context: ProjectContext, changes: dict, accept: list[str], reopen: list[str] | None = None) -> dict:
    """changes {question id: new answer}; accept [flaw keys] = keep the plan and accept the risk; reopen [keys] = take back an acceptance."""
    flaws = {flaw_key(f): f for f in _flaws(context)}
    changed = 0
    items = []
    for qid, text in (changes or {}).items():
        q = next((x for x in context.discovery_questions if x.id == qid), None)
        text = str(text or "").strip()
        if not q or not text or text == (q.answer or ""):
            continue
        f = next((f for f in flaws.values() if qid in (f.get("related_question_ids") or [])), {})
        items.append({"question_id": qid, "question": q.text, "answer": q.answer or "", "severity": f.get("severity", ""),
                      "flaw": str(f.get("flaw", ""))[:300], "suggestion": str(f.get("recommended_change", ""))[:300]})
        context.add_answer(qid, text)
        changed += 1
    if items:   # same shape remember_round() uses, so the next check knows what the founder changed and why
        context.feasibility_history.append({"round": len(context.feasibility_history) + 1, "verdict": "RETHINK", "items": items})
        context.feasibility_history[:] = context.feasibility_history[-6:]
        context.system_profile = None
    drop = set(reopen or [])
    context.accepted_flaws[:] = [a for a in context.accepted_flaws if a["key"] not in drop and a["key"] not in set(accept or [])]
    n = 0
    for k in accept or []:
        f = flaws.get(k)
        if f:
            context.accepted_flaws.append({"key": k, "flaw": f.get("flaw", ""), "severity": f.get("severity", ""),
                                           "sig": _sig(context, f), "at": datetime.now(timezone.utc).isoformat()})
            n += 1
    return {"changed": changed, "accepted": n}


def accepted_prompt_block(context: ProjectContext) -> str:
    acc = [a for a in context.accepted_flaws]
    if not acc:
        return ""
    lines = ["RISKS THE FOUNDER HAS KNOWINGLY ACCEPTED (they are keeping their plan):"] + [f"- [{a['severity']}] {a['flaw']}" for a in acc]
    lines.append("Do NOT raise these again as blocking flaws or keep grading them Critical on the same grounds; mention each once as a "
                 "residual risk with a plan-level mitigation, unless the answers behind them have changed.\n\n")
    return "\n".join(lines)

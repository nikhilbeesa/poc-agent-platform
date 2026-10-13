"""
Turns the Product Manager agent's output into tool-neutral backlog items, and renders each one for the tool that will
receive it (Jira: Atlassian Document Format, Azure DevOps: HTML).

Epic  = one product module        Story = one user story (US-nnn), titled with its ID so it stays traceable to the docs.
"""

from __future__ import annotations

import hashlib
import json
import re
from html import escape

import chunked as ch
from context import AgentRole, ProjectContext

PRIORITY_NAMES = {"high": "High", "medium": "Medium", "low": "Low"}


def _list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [] if s.lower() in ("", "none", "n/a", "[]") else [s]


def _text(v) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in ("none", "n/a") else s


def _label(s: str) -> str:
    """Jira labels cannot contain spaces; ADO tags are free text but the same form keeps them consistent."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s)).strip("-")[:50]


def snapshot_backlog(context: ProjectContext) -> dict:
    """The data the backlog is built from, in a small saveable form. Taken from the live Product Manager output when it
    exists (plus the UX screen/flow links the Definition of Ready/Done mention); otherwise whatever was saved earlier."""
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    if not pm or not (pm.output or {}).get("stories"):
        return dict(context.saved_backlog or {})
    o = pm.output
    ux = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)
    ux_o = (ux.output if ux else {}) or {}
    story_screens: dict[str, list] = {}
    story_flows: dict[str, list] = {}
    for sc in ux_o.get("screens", []):
        for sid in sc.get("related_story_ids", []):
            story_screens.setdefault(sid, []).append(sc.get("id"))
    for fl in ux_o.get("user_flows", []):
        for sid in fl.get("related_story_ids", []):
            story_flows.setdefault(sid, []).append(fl.get("id"))
    if not ux_o and context.saved_backlog:          # UX output not in memory: keep the links saved before
        story_screens = context.saved_backlog.get("story_screens", {})
        story_flows = context.saved_backlog.get("story_flows", {})
    return {"epics": o.get("epics", []), "stories": o.get("stories", []), "priorities": o.get("priorities", []),
            "story_screens": story_screens, "story_flows": story_flows}


def build_backlog(context: ProjectContext) -> dict:
    out = snapshot_backlog(context)
    prios = {p.get("story_id"): p for p in out.get("priorities", []) if isinstance(p, dict)}
    epics_by_id = {e["id"]: e for e in out.get("epics", []) if e.get("id")}

    from export import _story_dor_dod            # the user-stories document's own builder, so tools and document agree
    stories = []
    for s in out.get("stories", []):
        if not s.get("id"):
            continue
        epic = epics_by_id.get(s.get("epic_id"), {})
        rules = ch.normalize_validation_rules(s.get("data_validation"))
        dor, dod = _story_dor_dod(s, rules, [x for x in (out.get("story_screens") or {}).get(s["id"], []) if x],
                                  [x for x in (out.get("story_flows") or {}).get(s["id"], []) if x])
        prio = PRIORITY_NAMES.get(str((prios.get(s["id"]) or {}).get("priority", "")).lower(), "Medium")
        item = {
            "id": s["id"], "kind": "story", "epic_id": s.get("epic_id", ""),
            "title": f"{s['id']} · {_text(s.get('feature')) or _text(s.get('story'))[:80]}"[:250],
            "priority": prio, "role": _text(s.get("role")),
            "story": _text(s.get("story")), "business_value": _text(s.get("business_value")),
            "preconditions": _text(s.get("preconditions")), "trigger": _text(s.get("trigger")),
            "main_flow": _list(s.get("main_flow")), "alternative_flow": _text(s.get("alternative_flow")),
            "exception_flow": _text(s.get("exception_flow")), "business_rules": _list(s.get("business_rules")),
            "acceptance_criteria": _list(s.get("acceptance_criteria")), "edge_cases": _list(s.get("edge_cases"))[:8],
            "data_validation": rules, "error_messages": _list(s.get("error_messages")), "empty_states": _list(s.get("empty_states")),
            "dor": dor, "dod": dod,
            "dependencies": [d for d in _list(s.get("dependencies")) if re.match(r"^US-\d+$", d)],
            "fr_ids": _list(s.get("related_fr_ids")),
            "labels": ["ai-generated"] + [_label(epic.get("name", ""))] + [_label(f) for f in _list(s.get("related_fr_ids"))],
        }
        item["labels"] = [x for x in dict.fromkeys(item["labels"]) if x]
        item["hash"] = hashlib.sha1(json.dumps({k: v for k, v in item.items() if k != "hash"}, sort_keys=True).encode()).hexdigest()[:12]
        stories.append(item)

    epics = []
    for e in out.get("epics", []):
        item = {"id": e["id"], "kind": "epic", "title": f"{e['id']} · {_text(e.get('name'))}"[:250], "name": _text(e.get("name")),
                "description": _text(e.get("description")), "labels": ["ai-generated"],
                "story_count": sum(1 for s in stories if s["epic_id"] == e["id"])}
        item["hash"] = hashlib.sha1(json.dumps(item, sort_keys=True).encode()).hexdigest()[:12]
        epics.append(item)
    return {"epics": epics, "stories": stories}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _sections(it: dict) -> list[tuple[str, str, object]]:
    """(heading, kind, content) — kind: 'p' paragraph, 'ul' bullets, 'ol' numbered, 'table' {headers, rows}, 'check' checklist."""
    if it["kind"] == "epic":
        return [("", "p", it["description"])] if it["description"] else []
    rules = it.get("data_validation") or []
    table = {"headers": ["Field", "Field type", "Mandatory / Optional", "Validation rule"],
             "rows": [[r["field"], r["type"], r["mandatory"], r["rule"]] for r in rules]} if rules else None
    out = [("", "p", it["story"]), ("Business value", "p", it["business_value"]), ("Preconditions", "p", it["preconditions"]),
           ("Trigger", "p", it["trigger"]), ("Main flow", "ol", it["main_flow"]),
           ("Alternative flow", "p", it["alternative_flow"]), ("Exception flow", "p", it["exception_flow"]),
           ("Business rules", "ul", it["business_rules"]), ("Data validation", "table", table),
           ("Error messages", "ul", it.get("error_messages", [])), ("Empty states", "ul", it.get("empty_states", [])),
           ("Edge cases", "ul", it["edge_cases"])]
    return [x for x in out if x[2]]


def _closing_sections(it: dict) -> list[tuple[str, str, list[str]]]:
    """Definition of Ready / Done — after the acceptance criteria."""
    return [x for x in (("Definition of Ready (all must be true before development starts)", "check", it.get("dor", [])),
                        ("Definition of Done (all must be true before this story is accepted)", "check", it.get("dod", []))) if x[2]]


def _trace(it: dict) -> str:
    bits = []
    if it.get("fr_ids"):
        bits.append("Source requirement(s): " + ", ".join(it["fr_ids"]))
    if it.get("dependencies"):
        bits.append("Depends on: " + ", ".join(it["dependencies"]))
    bits.append(f"Backlog ID {it['id']} — generated by the AI product team; edit freely in this tool.")
    return " · ".join(bits)


def _html_block(head: str, kind: str, body) -> str:
    h = f"<h3>{escape(head)}</h3>" if head else ""
    if kind == "p":
        return h + f"<p>{escape(body)}</p>"
    if kind == "table":
        th = "".join(f"<th>{escape(c)}</th>" for c in body["headers"])
        tr = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in body["rows"])
        return h + f'<table border="1" cellpadding="4" style="border-collapse:collapse"><tr>{th}</tr>{tr}</table>'
    if kind == "check":
        return h + "<ul>" + "".join(f"<li>☐ {escape(x)}</li>" for x in body) + "</ul>"
    tag = "ol" if kind == "ol" else "ul"
    return h + f"<{tag}>" + "".join(f"<li>{escape(x)}</li>" for x in body) + f"</{tag}>"


def to_html(it: dict, with_acceptance: bool = False) -> str:
    """HTML for Azure DevOps. Acceptance criteria go in their own field where the process has one (see to_acceptance_html)."""
    h = [_html_block(*sec) for sec in _sections(it)]
    if with_acceptance and it.get("acceptance_criteria"):
        h.append("<h3>Acceptance criteria</h3>" + to_acceptance_html(it))
    h += [_html_block(*sec) for sec in _closing_sections(it)] if it["kind"] == "story" else []
    h.append(f"<p><i>{escape(_trace(it))}</i></p>")
    return "".join(h)


def to_acceptance_html(it: dict) -> str:
    return "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in it.get("acceptance_criteria", [])) + "</ul>"


def _adf_text(t: str, bold=False, italic=False) -> dict:
    n = {"type": "text", "text": t}
    marks = ([{"type": "strong"}] if bold else []) + ([{"type": "em"}] if italic else [])
    if marks:
        n["marks"] = marks
    return n


def _adf_cell(kind: str, text: str) -> dict:
    return {"type": kind, "attrs": {}, "content": [{"type": "paragraph", "content": [_adf_text(str(text) or "-", bold=(kind == "tableHeader"))]}]}


def to_adf(it: dict) -> dict:
    """Atlassian Document Format (Jira Cloud REST v3 requires it for description)."""
    para = lambda t, **k: {"type": "paragraph", "content": [_adf_text(t, **k)]}
    li = lambda t: {"type": "listItem", "content": [para(t)]}
    heading = lambda t: {"type": "heading", "attrs": {"level": 3}, "content": [_adf_text(t)]}

    def block(head, kind, body):
        c = [heading(head)] if head else []
        if kind == "p":
            c.append(para(body))
        elif kind == "table":
            rows = [{"type": "tableRow", "content": [_adf_cell("tableHeader", h) for h in body["headers"]]}]
            rows += [{"type": "tableRow", "content": [_adf_cell("tableCell", x) for x in row]} for row in body["rows"]]
            c.append({"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": rows})
        elif kind == "check":
            c.append({"type": "bulletList", "content": [li("☐ " + x) for x in body]})
        else:
            c.append({"type": "orderedList" if kind == "ol" else "bulletList", "content": [li(x) for x in body]})
        return c

    c = []
    for sec in _sections(it):
        c += block(*sec)
    if it.get("acceptance_criteria"):
        c += block("Acceptance criteria", "ul", it["acceptance_criteria"])
    if it["kind"] == "story":
        for sec in _closing_sections(it):
            c += block(*sec)
    c.append(para(_trace(it), italic=True))
    return {"type": "doc", "version": 1, "content": c}

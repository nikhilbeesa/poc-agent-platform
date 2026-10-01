"""
Artefact Export — fills the 6 Markdown templates with agent outputs.
Deterministic — pure string substitution/formatting, no AI involved here.

Produces exactly 6 documents:
  feasibility_assessment.md  (advisory, independent — NOT part of the Design AI handoff),
  business_requirements.md, user_stories.md, prd.md,
  ux_product_flow_specification.md, ai_handoff_validation.md

The BRD and PRD both render the shared system profile (expected scale, system, security,
performance and scalability requirements) from system_profile.py, so the two documents always
quote the same IDs and numbers.
"""

import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chunked as ch  # noqa: E402
from context import AgentRole, Artefact, ProjectContext, ProjectStage  # noqa: E402
import system_profile as sp  # noqa: E402
from agents.feasibility import DIMENSIONS  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "artefact_templates"
logger = get_logger()


def _fill_template(template_text: str, values: dict) -> str:
    text = template_text
    for key, val in values.items():
        if isinstance(val, list):
            val = "\n".join(f"- {item}" for item in val) if val else "- None specified"
        text = text.replace("{{" + key + "}}", str(val))
    text = re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "Not specified", text)
    return text


def _project_name(context: ProjectContext) -> str:
    return context.business_idea_raw[:60] or "Untitled Project"


def _date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bullets(items) -> str:
    if not items:
        return "- None specified"
    return "\n".join(f"- {i}" for i in items)


def _kv_block(d: dict) -> str:
    if not d:
        return "- None specified"
    lines = []
    for k, v in d.items():
        label = k.replace("_", " ").capitalize()
        if isinstance(v, list):
            v = "; ".join(str(x) for x in v) if v else "None specified"
        lines.append(f"- **{label}:** {v}")
    return "\n".join(lines)


def _table(headers: list, rows: list) -> str:
    """Render a GitHub-flavored Markdown table from a list of header
    strings and a list of row tuples/lists (each cell stringified and
    pipe-escaped)."""
    if not rows:
        return "*None specified.*"
    def esc(cell):
        return str(cell).replace("\n", " ").replace("|", "\\|")
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "|" + "|".join(["---"] * len(headers)) + "|"
    body = "\n".join("| " + " | ".join(esc(c) for c in row) + " |" for row in rows)
    return f"{header_row}\n{sep_row}\n{body}"



# ---------------------------------------------------------------------------
# Shared: system / security / scalability / performance profile + feasibility findings
# Rendered into BOTH the BRD and the PRD from the same profile (same IDs, same numbers).
# ---------------------------------------------------------------------------

def _profile_tables(context: ProjectContext) -> dict:
    prof = sp.profile_or_baseline(context)
    av = prof["availability"]
    scale = _table(["Parameter", "Value", "Basis"], [[r["parameter"], r["value"], r["basis"]] for r in prof["scale"]["rows"]])
    scale_notes = ""
    if prof["scale"]["assumptions"]:
        scale_notes = "\n\n**Assumptions used for planning**\n" + _bullets(prof["scale"]["assumptions"])
    return {
        "summary": prof["summary"],
        "scale": scale + scale_notes,
        "availability": (f"- **Availability target:** {av['uptime_target']} (allowed downtime: {av['allowed_downtime']})\n"
                         f"- **Recovery time objective (RTO):** {av['rto']}\n- **Recovery point objective (RPO):** {av['rpo']}\n"
                         f"- **Basis:** {av['basis']}"),
        "system": _table(["ID", "Category", "Requirement", "Priority", "Status"],
                         [[r["id"], r["category"], r["requirement"], r["priority"], r["status"]] for r in prof["system_requirements"]]),
        "security": _table(["ID", "Category", "Requirement", "How it is verified", "Priority", "Status"],
                           [[r["id"], r["category"], r["requirement"], r.get("verification", ""), r["priority"], r["status"]] for r in prof["security_requirements"]]),
        "performance": _table(["ID", "Metric", "Target", "Condition", "How it is measured", "Priority", "Status"],
                              [[r["id"], r["metric"], r["target"], r.get("condition", ""), r.get("measurement", ""), r["priority"], r["status"]] for r in prof["performance_requirements"]]),
        "scalability": _table(["ID", "Requirement", "Target", "Approach", "How it is verified", "Priority", "Status"],
                              [[r["id"], r["requirement"], r["target"], r.get("approach", ""), r.get("verification", ""), r["priority"], r["status"]] for r in prof["scalability_requirements"]]),
        "open_questions": prof["open_questions"],
    }


_STATUS_LEGEND = ("*Status: **Stated** = taken from your discovery answers; **Assumed — confirm** = a planning default because the question "
                  "was not answered; **Derived** = calculated from those volumes; **Proposed — confirm** = good-practice requirement that "
                  "needs your confirmation. Nothing marked Assumed or Proposed is a confirmed fact.*")


def _system_profile_markdown(context: ProjectContext, include_security: bool) -> str:
    t = _profile_tables(context)
    out = (f"### Expected scale and usage\n\n{t['summary']}\n\n{t['scale']}\n\n{_STATUS_LEGEND}\n\n"
           f"### Availability and recovery\n\n{t['availability']}\n\n"
           f"### System requirements\n\n{t['system']}\n\n"
           f"### Performance requirements\n\n{t['performance']}\n\n"
           f"### Scalability requirements\n\n{t['scalability']}")
    if include_security:
        out += f"\n\n### Security requirements\n\n{t['security']}"
    return out


def _feasibility_output(context: ProjectContext) -> dict:
    c = context.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    return c.output if c else {}


def _competitive_positioning_markdown(context: ProjectContext) -> str:
    """Short summary for the BRD/PRD; the full analysis lives in the Feasibility & Competitive Assessment."""
    o = _feasibility_output(context)
    if not o:
        return ""
    lines = []
    if o.get("positioning_statement"):
        lines.append(f"**Competitive positioning:** {o['positioning_statement']}")
    diffs = o.get("differentiators") or []
    if diffs:
        lines.append("**Key differentiators:**\n" + _bullets(
            f"{d.get('differentiator', '')} — {d.get('defensibility', '')} defensibility" for d in diffs[:5]))
    comps = o.get("competitors") or []
    if comps:
        lines.append("**Main alternatives:** " + "; ".join(f"{c.get('name', '')} ({c.get('type', '')})" for c in comps[:6]))
    lines.append(f"*Feasibility verdict: **{o.get('verdict', 'n/a')}**. See the Feasibility & Competitive Assessment document for the full analysis.*")
    return "\n\n".join(lines)


def _feasibility_risk_rows(context: ProjectContext) -> list[dict]:
    """Critical/major flaws from the feasibility assessment, shaped as BRD risk-register entries."""
    o = _feasibility_output(context)
    rows = []
    for f in o.get("flaws") or []:
        if f.get("severity") not in ("Critical", "Major"):
            continue
        critical = f["severity"] == "Critical"
        rows.append({
            "risk": f"{f.get('flaw', '')} (feasibility {f.get('id', '')})", "category": f"Feasibility — {f.get('area', '')}",
            "likelihood": "Medium", "severity": "High" if critical else "Medium",
            "rating": "High" if critical else "Medium", "score": 6 if critical else 4,
            "owner": "Product owner", "trigger": "Raised by the feasibility assessment",
            "consequence": f.get("why_it_matters", ""), "mitigation": f.get("recommended_change", ""),
        })
    return rows



# ---------------------------------------------------------------------------
# 0. Feasibility & Competitive Assessment (runs first; advisory)
# ---------------------------------------------------------------------------

def export_feasibility_assessment(context: ProjectContext) -> Artefact:
    c = context.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    o = c.output if c else {}
    template = (TEMPLATE_DIR / "feasibility_assessment.md").read_text()
    counts = o.get("counts", {})

    verdict_meaning = {
        "GO": "No blocking issues were found. Proceed, and validate the assumptions with real users.",
        "GO WITH CHANGES": "The idea is workable, but the flaws below should be addressed first.",
        "RETHINK": "The idea has serious problems as described and should be reworked before more effort is spent.",
    }
    verdict = o.get("verdict", "NOT ASSESSED")
    verdict_block = (
        f"**Verdict: {verdict}**  \n*{verdict_meaning.get(verdict, '')}*\n\n{o.get('verdict_rationale', '')}\n\n"
        f"- **Critical flaws:** {counts.get('critical', 0)}\n- **Major flaws:** {counts.get('major', 0)}\n"
        f"- **Minor flaws:** {counts.get('minor', 0)}\n- **Assessor confidence:** {o.get('confidence', 'n/a')}\n\n"
        "*The verdict is calculated from the severity of the flaws and the feasibility ratings; it cannot be more optimistic than they are.*"
    )

    competitors = _table(["Competitor / alternative", "Type", "What they do", "Strengths", "Weaknesses", "Pricing", "Threat"],
                         [[c_.get("name", ""), c_.get("type", ""), c_.get("what_they_do", ""), c_.get("strengths", ""),
                           c_.get("weaknesses", ""), c_.get("pricing_model", ""), c_.get("threat_level", "")] for c_ in o.get("competitors", [])])
    differentiators = _table(["Differentiator", "Description", "Competitors lacking it", "Defensibility", "Risk if copied"],
                             [[d.get("differentiator", ""), d.get("description", ""), d.get("competitors_lacking", ""),
                               d.get("defensibility", ""), d.get("risk_if_copied", "")] for d in o.get("differentiators", [])])
    labels = dict(DIMENSIONS)
    feasibility = _table(["Dimension", "Rating", "Assessment"],
                         [[labels.get(k, k), v.get("rating", ""), v.get("assessment", "")] for k, v in (o.get("feasibility") or {}).items()])
    flaws = _table(["ID", "Severity", "Area", "Flaw", "Why it matters", "Recommended change"],
                   [[f.get("id", ""), f.get("severity", ""), f.get("area", ""), f.get("flaw", ""), f.get("why_it_matters", ""),
                     f.get("recommended_change", "")] for f in o.get("flaws", [])])
    assumptions = _table(["Assumption", "How to validate it", "Risk if wrong"],
                         [[a.get("assumption", ""), a.get("how_to_validate", ""), a.get("risk_if_wrong", "")] for a in o.get("assumptions_to_validate", [])])
    top_changes = (o.get("recommended_changes") or [])[:5]
    revisit = o.get("questions_to_revisit") or []
    answers_to_revisit = (_table(["Question", "Current answer", "Why it needs a look", "Suggested change"],
                                 [[r.get("question", ""), (r.get("current_answer") or "").replace(" | ", ", ") or "(skipped)",
                                   " / ".join(x.get("flaw", "") for x in r.get("reasons", [])[:2]),
                                   r["reasons"][0].get("suggestion", "") if r.get("reasons") else ""] for r in revisit])
                          if revisit else "*No specific discovery answer was identified as the cause of a critical or major flaw.*")
    unlinked = o.get("unlinked_flaws") or []
    if unlinked:
        answers_to_revisit += "\n\n**Also flagged, but not tied to a single answer:**\n" + _bullets(
            f"{u['flaw']} — {u['suggestion']}" if u.get("suggestion") else u["flaw"] for u in unlinked)

    prof = sp.profile_or_baseline(context)
    scale_outlook = (f"{prof['summary']}\n\n*The full system, security, performance and scalability requirements are in the Business "
                     "Requirements Document (Non-Functional Requirements) and the PRD (sections 14-16).*")

    values = {
        "project_name": _project_name(context), "generated_date": _date(),
        "verdict_block": verdict_block, "evidence_note": o.get("evidence_note", "Not specified"),
        "headline_flaws": o.get("headline_flaws") or ["No critical or major flaws identified."],
        "top_changes": top_changes or ["None."],
        "idea_summary": o.get("idea_summary", context.business_idea_raw), "target_market": o.get("target_market", "Not specified"),
        "demand_signals": o.get("demand_signals", []), "market_risks": o.get("market_risks", []),
        "competitors": competitors, "competitive_gaps": o.get("competitive_gaps", []),
        "positioning_statement": o.get("positioning_statement", "Not specified"), "differentiators": differentiators,
        "feasibility": feasibility, "flaws": flaws, "assumptions_to_validate": assumptions,
        "recommended_changes": o.get("recommended_changes", []), "answers_to_revisit": answers_to_revisit,
        "must_confirm_before_build": o.get("must_confirm_before_build") or ["All scale, availability and data-sensitivity planning inputs were provided in the discovery answers."],
        "scale_outlook": scale_outlook,
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="feasibility_assessment",
                    title=f"Feasibility & Competitive Assessment — {values['project_name']}",
                    content_markdown=content, generated_by=AgentRole.FEASIBILITY_ASSESSMENT)


# ---------------------------------------------------------------------------
# 1. Business Requirements Document
# ---------------------------------------------------------------------------

def export_business_requirements(context: ProjectContext) -> Artefact:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    o = ba.output if ba else {}
    template = (TEMPLATE_DIR / "business_requirements.md").read_text()

    exec_sum = o.get("executive_summary", {})
    executive_summary = (
        f"**Product:** {exec_sum.get('product', 'Not specified')}\n\n"
        f"**Target users:** {exec_sum.get('target_users', 'Not specified')}\n\n"
        f"**Business opportunity / problem:** {exec_sum.get('opportunity', 'Not specified')}\n\n"
        f"**Proposed solution:** {exec_sum.get('solution', 'Not specified')}\n\n"
        f"**Expected business value:** {exec_sum.get('business_value', 'Not specified')}\n\n"
        f"**High-level capabilities:**\n" + _bullets(exec_sum.get("capabilities", []))
    )

    bg = o.get("business_background", {})
    business_background = "\n\n".join(
        f"**{label}:** {bg.get(key, 'Not specified')}"
        for key, label in [
            ("current_context", "Current business context"), ("existing_process", "Existing process"),
            ("market_situation", "Market / business situation"), ("why_needed", "Why the product is needed"),
            ("current_limitations", "Current limitations"), ("business_opportunity", "Business opportunity"),
        ]
    )

    problem_statement = _table(["Problem Area", "Current Pain Point", "Business Impact"],
                                [[p.get("area", ""), p.get("pain_point", ""), p.get("impact", "")] for p in o.get("problem_statement", [])])

    pv = o.get("product_vision", {})
    product_vision = "\n\n".join(
        f"**{label}:** {pv.get(key, 'Not specified')}"
        for key, label in [("vision", "Product vision"), ("future_state", "Desired future state"),
                             ("long_term_direction", "Long-term business direction"), ("value_proposition", "Core value proposition")]
    )

    positioning = _competitive_positioning_markdown(context)
    if positioning:
        product_vision += "\n\n" + positioning

    kpis = _table(["KPI", "Definition", "Target", "Measurement Method"],
                  [[k.get("kpi", ""), k.get("definition", ""), k.get("target", "TBD"), k.get("measurement", "")] for k in o.get("kpis", [])])

    stakeholders = _table(["Stakeholder", "Responsibility / Interest", "Decision Authority"],
                           [[s.get("stakeholder", ""), s.get("interest", ""), s.get("authority", "")] for s in o.get("stakeholders", [])])

    def _render_role(r: dict) -> str:
        return (f"#### {r.get('role', '?')}\n"
                f"- **Purpose:** {r.get('purpose', 'N/A')}\n- **Responsibilities:** {r.get('responsibilities', 'N/A')}\n"
                f"- **Main capabilities:** {r.get('capabilities', 'N/A')}\n- **Permissions:** {r.get('permissions', 'N/A')}\n"
                f"- **Restricted actions:** {r.get('restricted', 'N/A')}\n")
    roles_list = o.get("roles", [])
    roles_text = "\n".join(_render_role(r) for r in roles_list) or "*None specified.*"
    roles_table = _table(["Role", "Core Permissions"], [[r.get("role", ""), r.get("permissions", "")] for r in roles_list])
    roles = f"{roles_text}\n\n{roles_table}"

    def _render_persona(p: dict) -> str:
        return (f"#### {p.get('name', '?')}\n"
                f"- **Role:** {p.get('role', 'N/A')}\n- **Occupation:** {p.get('occupation', 'N/A')}\n"
                f"- **Goals:** {p.get('goals', 'N/A')}\n- **Needs:** {p.get('needs', 'N/A')}\n"
                f"- **Pain points:** {p.get('pain_points', 'N/A')}\n- **Behaviors:** {p.get('behaviors', 'N/A')}\n"
                f"- **Expectations:** {p.get('expectations', 'N/A')}\n")
    user_personas = "\n".join(_render_persona(p) for p in o.get("user_personas", [])) or "*None specified.*"

    user_journeys = "\n\n".join(f"**{name}:** {desc}" for name, desc in o.get("user_journeys", {}).items()) or "*None specified.*"

    modules = _table(["Module ID", "Module", "Purpose"], [[m.get("id", ""), m.get("name", ""), m.get("purpose", "")] for m in o.get("modules", [])])

    requirements = _table(["ID", "Requirement Name", "Module", "Description", "Primary Actor", "Priority", "Rationale", "Dependencies", "Status"],
                           [[r.get("id", ""), r.get("name", ""), r.get("module", ""), r.get("description", ""), r.get("actor", ""),
                             r.get("priority", ""), r.get("rationale", ""), ", ".join(r.get("dependencies", []) or []) or "None",
                             r.get("status", "Draft")] for r in o.get("requirements", [])])

    def _render_module_detail(m: dict) -> str:
        return (f"#### {m.get('module', '?')}\n"
                f"- **Purpose:** {m.get('purpose', 'N/A')}\n- **Actors:** {m.get('actors', 'N/A')}\n"
                f"- **Inputs:** {m.get('inputs', 'N/A')}\n- **Processing:** {m.get('processing', 'N/A')}\n"
                f"- **Outputs:** {m.get('outputs', 'N/A')}\n- **Business rules:** {m.get('business_rules', 'N/A')}\n"
                f"- **Dependencies:** {m.get('dependencies', 'N/A')}\n- **Priority:** {m.get('priority', 'N/A')}\n")
    module_details = "\n".join(_render_module_detail(m) for m in o.get("module_details", [])) or "*None specified.*"

    business_rules = _table(["Rule ID", "Business Rule"], [[b.get("id", ""), b.get("rule", "")] for b in o.get("business_rules", [])])

    nfrs = _table(["ID", "Category", "Requirement", "Priority", "Target", "Verification Method"],
                   [[n.get("id", ""), n.get("category", ""), n.get("requirement", ""), n.get("priority", ""),
                     n.get("target", "TBD"), n.get("verification_method", "TBD")] for n in o.get("nfrs", [])])
    nfr_details = "\n".join(
        f"**{n.get('id', '?')} — {n.get('category', '')}**  \n"
        f"*Measurement:* {n.get('measurement', 'TBD')}  \n"
        f"*Related module:* {n.get('related_module', 'All modules')}  \n"
        f"*Dependencies:* {', '.join(n.get('dependencies', []) or []) or 'None'}  \n"
        f"*Source:* {n.get('source', 'N/A')} | *Status:* {n.get('status', 'Draft')}\n"
        for n in o.get("nfrs", [])
    ) or "*None specified.*"
    nfrs = f"{nfrs}\n\n**NFR detail:**\n\n{nfr_details}"
    # scale, availability, system, performance and scalability requirements (shared with the PRD)
    nfrs += "\n\n" + _system_profile_markdown(context, include_security=False)

    def _render_entity(e: dict) -> str:
        return f"**{e.get('entity', '?')}:**\n" + _bullets(e.get("fields", []))
    data_entities = "\n\n".join(_render_entity(e) for e in o.get("data_entities", [])) or "*None specified.*"
    data_relationships = _bullets(o.get("data_relationships", []))

    data_classification = _table(["Classification", "Examples", "Access Requirements"],
                                  [[d.get("level", ""), d.get("examples", ""), d.get("access", "")] for d in o.get("data_classification", [])])

    notifications_matrix = _table(["Event", "Customer", "Provider", "Admin/Support", "Channel"],
                                   [[n.get("event", ""), n.get("customer", n.get("buyer", "")), n.get("provider", n.get("seller", "")), n.get("admin", ""), n.get("channel", "")] for n in o.get("notifications_matrix", [])])

    pr = o.get("payment_requirements")
    payment_requirements = (_kv_block(pr) if pr else "*Not applicable — this product does not currently involve direct payment processing per the discovery answers.*")

    admin_operations = _kv_block(o.get("admin_operations", {}))

    reporting_groups = o.get("reporting", [])
    reporting = "\n".join(f"**{g.get('group', '?')}:** " + ", ".join(g.get("reports", [])) for g in reporting_groups) or "*None specified.*"
    analytics_events = _bullets(o.get("analytics_events", []))

    security_requirements = _bullets(o.get("security_requirements", []))
    threats = _table(["Threat", "Example Control"], [[t.get("threat", ""), t.get("control", "")] for t in o.get("threats", [])])
    security_requirements = f"{security_requirements}\n\n**Threats & controls:**\n\n{threats}"
    security_requirements += f"\n\n### Security requirements (SEC)\n\n{_profile_tables(context)['security']}"

    integrations = _table(["Integration", "Purpose", "Key Requirements"],
                           [[i.get("integration", ""), i.get("purpose", ""), i.get("requirements", "")] for i in o.get("integrations", [])])

    mvp = o.get("mvp_prioritization", {})
    mvp_rows = []
    for tier, label in [("P0", "P0 — Critical"), ("P1", "P1 — Must Have"), ("P2", "P2 — Should Have"), ("P3", "P3 — Could Have"), ("out_of_scope", "Out of Scope")]:
        for item in mvp.get(tier, []):
            mvp_rows.append([label, item])
    mvp_prioritization = _table(["Tier", "Capability"], mvp_rows)

    user_stories_summary = _table(["ID", "Title", "Actor", "Story", "Priority", "Related FR"],
                                   [[s.get("id", ""), s.get("title", ""), s.get("actor", ""), s.get("story", ""), s.get("priority", ""), s.get("related_fr", "")] for s in o.get("user_stories_summary", [])])

    def _render_ac(a: dict) -> str:
        return f"**{a.get('capability', '?')}**\n" + _bullets(a.get("criteria", []))
    acceptance_criteria_summary = "\n\n".join(_render_ac(a) for a in o.get("acceptance_criteria_summary", [])) or "*See the User Stories document for full acceptance criteria.*"

    traceability_matrix = _table(["BRD Area", "Functional Requirement", "User Story", "Module", "QA Reference", "Priority"],
                                  [[t.get("brd_area", ""), t.get("fr", ""), t.get("user_story", ""), t.get("module", ""), t.get("qa_reference", ""), t.get("priority", "")] for t in o.get("traceability_matrix", [])])

    release_strategy = "\n".join(
        f"**{r.get('phase', '?')}:** {r.get('description', '')}  \n*Exit criteria: {r.get('exit_criteria', '')}*\n"
        for r in o.get("release_strategy", [])
    ) or "*None specified.*"

    glossary = _table(["Term", "Definition"], [[g.get("term", ""), g.get("definition", "")] for g in o.get("glossary", [])])

    document_control = _kv_block({
        "status": "Draft — generated by AI Business Analyst Agent",
        "version": "1.0",
        "prepared_for": "Downstream Product, UX, and Design AI agents",
    })

    # --- depth sections: envisioned flow diagrams, ranked risk register, key parameters ---
    diagrams = o.get("flow_diagrams") or []
    future_flow_section = str(o.get("future_state_flow", "Not specified"))
    if diagrams:
        future_flow_section += "\n\n**Envisioned flow diagrams**\n\n" + "\n\n".join(
            f"*{d.get('title', 'Flow')}*" + (f" — {d['description']}" if d.get("description") else "")
            + f"\n\n```mermaid\n{d.get('mermaid', '')}\n```" for d in diagrams
        )

    all_risks = list(o.get("risks", [])) + _feasibility_risk_rows(context)
    all_risks.sort(key=lambda r: -(r.get("score") or 0))          # highest-rated first (stable for unscored)
    risk_rows = [
        [r.get("risk", ""), r.get("category", "") or "-", r.get("likelihood") or "Not assessed",
         r.get("severity") or r.get("impact", "") or "Not assessed",
         f"{r.get('rating', 'Not assessed')} ({r.get('score', 0)})" if r.get("score") else "Not assessed",
         r.get("owner", "") or "Unassigned", r.get("trigger", "") or "-",
         r.get("consequence", "") or r.get("impact", ""), r.get("mitigation", "")]
        for r in all_risks
    ]
    risks_section = (
        "*Rating = Likelihood x Severity (Low=1, Medium=2, High=3): 6-9 High, 3-4 Medium, 1-2 Low. "
        "Risks are listed highest-rated first.*\n\n"
        + _table(["Risk", "Category", "Likelihood", "Severity", "Rating", "Owner", "Early-warning trigger",
                  "Consequence", "Mitigation"], risk_rows)
    )

    kp = o.get("key_parameters") or []
    key_parameters_section = ""
    if kp:
        key_parameters_section = (
            "\n\n**Key business parameters and thresholds**\n\n"
            "*Concrete values the requirements depend on. \"Proposed default\" values need business confirmation; "
            "\"TBD\" items are listed under Open Questions.*\n\n"
            + _table(["Parameter", "Value", "Status", "Related", "Owner"],
                     [[p.get("parameter", ""), p.get("value", ""), p.get("status", ""), p.get("related", "") or "-",
                       p.get("owner", "") or "-"] for p in kp])
        )

    values = {
        "project_name": _project_name(context),
        "domain_classification": context.domain_classification or "Unclassified",
        "generated_date": _date(),
        "document_control": document_control,
        "executive_summary": executive_summary,
        "business_background": business_background,
        "problem_statement": problem_statement,
        "product_vision": product_vision,
        "business_objectives": o.get("business_objectives", []),
        "kpis": kpis,
        "scope_in": o.get("scope_in", []),
        "scope_out": o.get("scope_out", []),
        "non_goals": o.get("non_goals", []),
        "stakeholders": stakeholders,
        "roles": roles,
        "user_personas": user_personas,
        "current_state_process": o.get("current_state_process", "Not specified"),
        "current_state_flow": o.get("current_state_flow", "Not specified"),
        "future_state_process": o.get("future_state_process", "Not specified"),
        "future_state_flow": future_flow_section,
        "user_journeys": user_journeys,
        "modules": modules,
        "requirements": requirements,
        "module_details": module_details,
        "business_rules": business_rules + key_parameters_section,
        "nfrs": nfrs,
        "data_entities": data_entities,
        "data_relationships": data_relationships,
        "data_classification": data_classification,
        "notifications_matrix": notifications_matrix,
        "payment_requirements": payment_requirements,
        "admin_operations": admin_operations,
        "reporting": reporting,
        "analytics_events": analytics_events,
        "security_requirements": security_requirements,
        "privacy_compliance": o.get("privacy_compliance", "Applicable privacy and regulatory requirements must be confirmed for the launch geography."),
        "accessibility": o.get("accessibility", []),
        "integrations": integrations,
        "assumptions": o.get("assumptions", []),
        "constraints": o.get("constraints", []),
        "dependencies": o.get("dependencies", []),
        "risks": risks_section,
        "mvp_prioritization": mvp_prioritization,
        "user_stories_summary": user_stories_summary,
        "acceptance_criteria_summary": acceptance_criteria_summary,
        "traceability_matrix": traceability_matrix,
        "release_strategy": release_strategy,
        "future_enhancements": o.get("future_enhancements", []),
        "glossary": glossary,
        "open_questions": list(o.get("open_questions", [])) + [
            f"Decision needed — {p['parameter']}: {p['value']}"
            for p in o.get("key_parameters", []) if str(p.get("status", "")).upper() == "TBD"
        ],
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="business_requirements",
                     title=f"Business Requirements — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.BUSINESS_ANALYST)


# ---------------------------------------------------------------------------
# 2. User Stories Document
# ---------------------------------------------------------------------------

def _story_dor_dod(story: dict, rules: list, screens: list, flows: list) -> tuple[list, list]:
    """Definition of Ready / Done for ONE story, built from that story's own content
    (its dependencies, fields, messages and acceptance criteria) rather than a
    generic checklist shared by the whole backlog."""
    sid = story.get("id", "This story")
    frs = ", ".join(story.get("related_fr_ids", [])) or "its source requirement"
    deps = story.get("dependencies") or []
    n_flow = len(story.get("main_flow") or [])
    n_ac = len(story.get("acceptance_criteria") or [])
    n_msg = len(story.get("error_messages") or [])
    n_edge = len([e for e in (story.get("edge_cases") or []) if str(e).strip()])
    n_rules = len(story.get("business_rules") or [])
    mandatory = [r["field"] for r in rules if r["mandatory"] == "Mandatory"]
    optional = [r["field"] for r in rules if r["mandatory"] == "Optional"]
    empties = story.get("empty_states") or []
    has_empty = bool(empties) and not str(empties[0]).startswith("Not applicable")

    dor = [
        f"{sid} is linked to {story.get('epic_id') or 'an epic'} and traces back to {frs}.",
        f"Actor ({story.get('role', 'role')}), preconditions and trigger are written down and agreed.",
        f"The main flow ({n_flow} steps), the alternative flow and the exception flow are described.",
        f"Data validation is defined for {len(rules)} field(s), each with a field type and marked Mandatory or Optional"
        + (f" ({len(mandatory)} mandatory, {len(optional)} optional)." if rules else "."),
        f"{n_ac} Given/When/Then acceptance criteria are written and testable, including validation, error and permission cases.",
        (f"Dependencies {', '.join(deps)} are Done or sequenced ahead of this story." if deps
         else "No story dependencies — this story can be started independently."),
        (f"The {n_rules} business rule(s) listed above are confirmed with the Product Owner." if n_rules
         else "No module-level business rules apply beyond the validation above."),
        "Any Open Question (see Open Questions) that blocks this story is resolved.",
        "The story is small enough to be completed within one sprint and has been estimated by the team.",
    ]
    dod = [
        f"All {n_ac} acceptance criteria pass, including the negative and permission cases.",
        f"Behaviour matches {frs} and the business rule(s) referenced in the story.",
        (f"All {len(rules)} field validations are enforced on both client and server; mandatory fields "
         f"({', '.join(mandatory[:4])}{'…' if len(mandatory) > 4 else ''}) reject blank input and field types are checked."
         if mandatory else f"All {len(rules)} field validations are enforced on both client and server, with field types checked."
         if rules else "Permission and state checks described in the validation section are enforced server-side."),
        f"The {n_msg} error message(s) are shown with the exact wording defined in this story." if n_msg
        else "Failures show a specific, user-friendly message rather than a generic error.",
        ("The empty state is implemented with its message and call-to-action." if has_empty
         else "Empty state is not applicable to this story and has been confirmed as such."),
        f"The {n_edge} edge case(s) are handled and verified, and no partial data is ever saved." if n_edge
        else "Boundary and unusual situations do not leave partial data behind.",
        ("UX review completed against " + ", ".join(screens + flows) + "." if (screens or flows)
         else "UX screens/flows for this story are reviewed once the UX Product Flow Specification is available."),
        (f"No regression in dependency stories {', '.join(deps)}." if deps else "No regression in existing functionality."),
        "Code is peer-reviewed, automated tests are added and passing, and the story is deployed to the test environment.",
        "The Product Owner has accepted the story in the demo/review.",
    ]
    return dor, dod


def export_user_stories(context: ProjectContext) -> Artefact:
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    ux = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)
    o = pm.output if pm else {}
    ba_o = ba.output if ba else {}
    prd_o = prd.output if prd else {}
    ux_o = ux.output if ux else {}
    template = (TEMPLATE_DIR / "user_stories.md").read_text()

    epics = o.get("epics", [])
    stories = o.get("stories", [])
    requirements = ba_o.get("requirements", [])

    epics_list = "\n".join(f"- **{e['id']}: {e['name']}** — {e['description']}" for e in epics) or "- None generated"

    document_control = _kv_block({
        "status": "Draft — generated by AI Product Manager Agent",
        "version": "1.0",
        "source_documents": "Business Requirements Document (functional requirements, business rules, roles)",
        "prepared_for": "Engineering, QA, and downstream UX/Design AI agents",
    })

    exec_sum = ba_o.get("executive_summary", {})
    product_context = (
        f"**Product:** {exec_sum.get('product') or context.business_idea_raw}\n\n"
        f"**Domain:** {context.domain_classification or 'Unclassified'}\n\n"
        f"**Target users:** {ba_o.get('target_users') or exec_sum.get('target_users', 'Not specified')}\n\n"
        f"This backlog decomposes every functional requirement in the Business "
        f"Requirements Document ({len(requirements)} total) into actionable, "
        f"independently testable user stories."
    )

    methodology = (
        "Every functional requirement identified in the Business Requirements "
        "Document (FR-IDs) was converted into exactly one user story, grouped "
        "into epics that align 1:1 with the product modules defined there. No "
        "requirement was sampled, summarized, or dropped in this conversion — "
        "each story keeps a direct `related_fr_ids` reference back to its "
        "source requirement so the two documents stay traceable. Stories are "
        "not a restatement of the requirement; each adds actor-level detail "
        "(preconditions, trigger, main/alternative/exception flow, data "
        "validation rules, exact error messages, empty states, edge cases, and "
        "Given/When/Then acceptance criteria) that the requirement itself "
        "does not specify."
    )

    def _render_persona_brief(p: dict) -> str:
        return f"- **{p.get('name', '?')}** ({p.get('role', 'N/A')}): {p.get('goals', 'N/A')}"
    personas_list = ba_o.get("user_personas", [])
    personas = "\n".join(_render_persona_brief(p) for p in personas_list) or "- None specified — see Business Requirements Document Section 11."

    fr_to_stories = {}
    for s in stories:
        for fr_id in s.get("related_fr_ids", []):
            fr_to_stories.setdefault(fr_id, []).append(s["id"])
    feature_inventory = _table(
        ["Feature (FR) ID", "Feature Name", "Module", "Priority", "Covering Story ID(s)"],
        [[r.get("id", ""), r.get("name", ""), r.get("module", ""), r.get("priority", ""),
          ", ".join(fr_to_stories.get(r.get("id", ""), [])) or "Not yet covered"] for r in requirements],
    )

    screens = ux_o.get("screens", [])
    flows = ux_o.get("user_flows", [])
    story_to_screens, story_to_flows = {}, {}
    for sc in screens:
        for sid in sc.get("related_story_ids", []):
            story_to_screens.setdefault(sid, []).append(sc["id"])
    for fl in flows:
        for sid in fl.get("related_story_ids", []):
            story_to_flows.setdefault(sid, []).append(fl["id"])

    def _render_story(s: dict) -> str:
        lines = [
            f"### {s.get('id', '?')} — {s.get('feature', 'Untitled')}",
            f"*Epic: {s.get('epic_id', '-')}  |  Role: {s.get('role', '-')}  |  Related requirement(s): {', '.join(s.get('related_fr_ids', [])) or 'N/A'}*",
            "",
            f"**Story:** {s.get('story', '')}",
            f"**Business value:** {s.get('business_value', 'Not specified')}",
            f"**Preconditions:** {s.get('preconditions', 'Not specified')}",
            f"**Trigger:** {s.get('trigger', 'Not specified')}",
            "",
            "**Main flow:**",
        ]
        for i, step in enumerate(s.get("main_flow", []), start=1):
            lines.append(f"  {i}. {step}")
        lines.append(f"\n**Alternative flow:** {s.get('alternative_flow', 'None')}")
        lines.append(f"**Exception flow:** {s.get('exception_flow', 'None')}")
        rules = ch.normalize_validation_rules(s.get("data_validation"))
        if rules:
            lines.append("\n**Data validation:**\n")
            lines.append(_table(["Field", "Field type", "Mandatory / Optional", "Validation rule"],
                                [[r["field"], r["type"], r["mandatory"], r["rule"]] for r in rules]))
        for label, key in (("Error messages", "error_messages"),
                           ("Empty states", "empty_states"), ("Edge cases", "edge_cases")):
            items = s.get(key) or []
            if items:
                lines.append(f"\n**{label}:**")
                lines.extend(f"- {i}" for i in items)
        if s.get("business_rules"):
            lines.append("\n**Business rules:**")
            lines.extend(f"- {r}" for r in s["business_rules"])
        if s.get("acceptance_criteria"):
            lines.append("\n**Acceptance criteria:**")
            lines.extend(f"- {c}" for c in s["acceptance_criteria"])
        dor, dod = _story_dor_dod(s, rules, story_to_screens.get(s.get("id"), []), story_to_flows.get(s.get("id"), []))
        lines.append("\n**Definition of Ready** *(all must be true before development starts):*")
        lines.extend(f"- [ ] {i}" for i in dor)
        lines.append("\n**Definition of Done** *(all must be true before this story is accepted):*")
        lines.extend(f"- [ ] {i}" for i in dod)
        return "\n".join(lines) + "\n\n---\n"

    stories_list = "\n".join(_render_story(s) for s in stories) or "None generated"

    priorities = o.get("priorities", [])
    priority_rows = "\n".join(
        f"| {p['story_id']} | {p['priority']} | {p.get('notes', '')} |" for p in priorities
    ) or "| - | - | - |"
    story_priority = {p["story_id"]: p["priority"] for p in priorities}

    dependency_lines = [
        f"- **{s['id']}** ({s.get('feature', '')}) depends on: {', '.join(s['dependencies'])}"
        for s in stories if s.get("dependencies")
    ]
    dependencies_blockers = "\n".join(dependency_lines) or (
        "- No cross-story dependencies identified. Each story's own "
        "preconditions and business rules should still be checked before "
        "starting work on it."
    )

    release_rows = []
    for s in stories:
        pri = story_priority.get(s["id"], "Medium")
        release = {"High": "MVP", "Medium": "Post-MVP — Phase 1", "Low": "Future / Backlog"}[pri]
        release_rows.append([s["id"], s.get("feature", ""), pri, release])
    release_mapping = _table(["Story ID", "Feature", "Priority", "Suggested Release"], release_rows)

    traceability_rows = [
        [s["id"], s.get("epic_id", ""), ", ".join(s.get("related_fr_ids", [])) or "N/A",
         ", ".join(story_to_screens.get(s["id"], [])) or ("Pending UX handoff" if not ux_o else "N/A"),
         ", ".join(story_to_flows.get(s["id"], [])) or ("Pending UX handoff" if not ux_o else "N/A")]
        for s in stories
    ]
    story_traceability = _table(["Story ID", "Epic ID", "Related FR", "Related UX Screen(s)", "Related UX Flow(s)"], traceability_rows)

    open_questions = ba_o.get("open_questions", []) or ["None outstanding — all discovery questions were answered"]

    fr_covered = len(fr_to_stories)
    priority_counts = {}
    for p in priorities:
        priority_counts[p["priority"]] = priority_counts.get(p["priority"], 0) + 1
    completeness_summary = _kv_block({
        "epics": len(epics),
        "stories": len(stories),
        "functional_requirements_in_brd": len(requirements),
        "functional_requirements_covered_by_a_story": f"{fr_covered} / {len(requirements)}",
        "priority_breakdown": ", ".join(f"{k}: {v}" for k, v in priority_counts.items()) or "N/A",
        "stories_with_declared_dependencies": len(dependency_lines),
        "open_questions_outstanding": 0 if open_questions == ["None outstanding — all discovery questions were answered"] else len(open_questions),
        "ux_traceability_available": "Yes" if screens or flows else "Not yet — generate the UX Product Flow Specification to complete this mapping",
    })

    values = {
        "project_name": _project_name(context),
        "domain_classification": context.domain_classification or "Unclassified",
        "generated_date": _date(),
        "document_control": document_control,
        "product_context": product_context,
        "methodology": methodology,
        "personas": personas,
        "epics_list": epics_list,
        "feature_inventory": feature_inventory,
        "stories_list": stories_list,
        "priority_table_rows": priority_rows,
        "dependencies_blockers": dependencies_blockers,
        "release_mapping": release_mapping,
        "story_traceability": story_traceability,
        "open_questions": open_questions,
        "completeness_summary": completeness_summary,
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="user_stories",
                     title=f"User Stories — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.PRODUCT_MANAGER)


# ---------------------------------------------------------------------------
# 3. Product Requirements Document (PRD)
# ---------------------------------------------------------------------------

def export_prd(context: ProjectContext) -> Artefact:
    prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    o = prd.output if prd else {}
    template = (TEMPLATE_DIR / "prd.md").read_text()

    personas_text = "\n".join(
        f"- **{p.get('name', '?')}** ({p.get('role', '?')}) — {p.get('goals', '')}" for p in o.get("personas", [])
    ) or "- None specified"

    def _render_fr(fr: dict) -> str:
        return (
            f"### {fr.get('id', '?')} — {fr.get('feature', 'Untitled')}\n"
            f"- **Purpose:** {fr.get('purpose', 'N/A')}\n"
            f"- **Actor:** {fr.get('actor', 'N/A')}\n"
            f"- **Trigger:** {fr.get('trigger', 'N/A')}\n"
            f"- **Preconditions:** {fr.get('preconditions', 'N/A')}\n"
            f"- **Inputs:** {', '.join(fr.get('inputs', [])) or 'N/A'}\n"
            f"- **Expected behavior:** {fr.get('expected_behavior', 'N/A')}\n"
            f"- **Outputs:** {', '.join(fr.get('outputs', [])) or 'N/A'}\n"
            f"- **User-visible result:** {fr.get('user_visible_result', 'N/A')}\n"
            f"- **Validation:** {fr.get('validation', 'N/A')}\n"
            f"- **Error scenarios:** {', '.join(fr.get('error_scenarios', [])) or 'N/A'}\n"
            f"- **Dependencies:** {', '.join(fr.get('dependencies', [])) or 'N/A'}\n"
        )
    fr_text = "\n".join(_render_fr(fr) for fr in o.get("functional_requirements", [])) or "None generated."

    roles_text = "\n".join(
        f"- **{r.get('role', '?')}:** {', '.join(r.get('permissions', []))}" for r in o.get("roles_and_permissions", [])
    ) or "- None specified"

    milestones = "\n".join(
        f"- **{m.get('milestone', '?')}**: {m.get('description', '')}" for m in o.get("release_milestones", [])
    ) or "- None specified"

    def _kv_block_with_notes(d: dict, notes_key: str, notes_label: str) -> str:
        base = dict(d)
        capability_notes = base.pop(notes_key, [])
        text = _kv_block(base)
        if capability_notes:
            notes_text = "\n".join(f"  - **{n.get('capability', '?')}:** {n.get('note', '')}" for n in capability_notes)
            text += f"\n- **{notes_label}:**\n{notes_text}"
        return text

    def _render_ai_feature(f: dict) -> str:
        return (
            f"### {f.get('feature', 'Untitled AI Feature')}" + (f" ({f['related_fr']})" if f.get("related_fr") else "") + "\n"
            f"- **Purpose:** {f.get('purpose', 'N/A')}\n"
            f"- **Input data:** {f.get('input_data', 'N/A')}\n"
            f"- **Trigger:** {f.get('trigger', 'N/A')}\n"
            f"- **Processing behavior:** {f.get('processing_behavior', 'N/A')}\n"
            f"- **Output:** {f.get('output', 'N/A')}\n"
            f"- **Confidence handling:** {f.get('confidence_handling', 'N/A')}\n"
            f"- **Explainability:** {f.get('explainability', 'N/A')}\n"
            f"- **User control:** {f.get('user_control', 'N/A')}\n"
            f"- **Edit/override behavior:** {f.get('edit_override_behavior', 'N/A')}\n"
            f"- **Failure behavior:** {f.get('failure_behavior', 'N/A')}\n"
            f"- **Fallback behavior:** {f.get('fallback_behavior', 'N/A')}\n"
            f"- **Privacy considerations:** {f.get('privacy_considerations', 'N/A')}\n"
            f"- **Data usage:** {f.get('data_usage', 'N/A')}\n"
            f"- **Security considerations:** {f.get('security_considerations', 'N/A')}\n"
            f"- **Performance expectations:** {f.get('performance_expectations', 'N/A')}\n"
        )
    ai_features_text = "\n".join(_render_ai_feature(f) for f in o.get("ai_feature_specifications", [])) or \
        "*This product has no AI-powered features per the business idea and discovery answers.*"

    t = _profile_tables(context)
    positioning = _competitive_positioning_markdown(context)
    nfr_list = o.get("non_functional_requirements", [])
    nfr_text = (_bullets(nfr_list) if nfr_list else "*None specified.*")
    nfr_text += (f"\n\n### Expected scale and usage\n\n{t['summary']}\n\n{t['scale']}\n\n{_STATUS_LEGEND}\n\n"
                 f"### Availability and recovery\n\n{t['availability']}\n\n"
                 f"### Performance requirements\n\n{t['performance']}\n\n"
                 f"### Scalability requirements\n\n{t['scalability']}")

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "product_overview": o.get("product_overview", "Not specified") + (("\n\n" + positioning) if positioning else ""),
        "product_goals": o.get("product_goals", []),
        "target_users": o.get("target_users", "Not specified"),
        "personas": personas_text,
        "user_journeys": o.get("user_journeys", []),
        "product_capabilities": o.get("product_capabilities", []),
        "functional_requirements": fr_text,
        "roles_and_permissions": roles_text,
        "product_business_rules": o.get("product_business_rules", []),
        "navigation_pattern": o.get("navigation_pattern", "Not specified"),
        "navigation_behavior": o.get("navigation_behavior", "Not specified"),
        "notifications_and_confirmations": o.get("notifications_and_confirmations", []),
        "validation_and_error_handling": o.get("validation_and_error_handling", "Not specified"),
        "state_behaviors": _kv_block(o.get("state_behaviors", {})),
        "audit_and_versioning": o.get("audit_and_versioning", "Not specified"),
        "non_functional_requirements": nfr_text,
        "technical_integration_constraints": _kv_block_with_notes(o.get("technical_integration_constraints", {}), "capability_technical_notes", "Per-capability technical notes")
            + f"\n\n### System requirements\n\n{t['system']}",
        "security_privacy_access_constraints": _kv_block_with_notes(o.get("security_privacy_access_constraints", {}), "capability_security_notes", "Per-capability security notes")
            + f"\n\n### Security requirements\n\n{t['security']}",
        "ai_feature_specifications": ai_features_text,
        "mvp_scope": o.get("mvp_scope", []) or ["Not specified"],
        "phase_2_scope": o.get("phase_2_scope", []) or ["None specified"],
        "future_scope": o.get("future_scope", []) or ["None specified"],
        "success_metrics": o.get("success_metrics", []),
        "out_of_scope": o.get("out_of_scope", []),
        "dependencies": o.get("dependencies", []),
        "assumptions": o.get("assumptions", []),
        "release_milestones": milestones,
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="prd",
                     title=f"PRD — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.PRODUCT_REQUIREMENTS)


# ---------------------------------------------------------------------------
# 4. UX / Product Flow Specification
# ---------------------------------------------------------------------------

def export_ux_product_flow(context: ProjectContext) -> Artefact:
    ux = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)
    o = ux.output if ux else {}
    template = (TEMPLATE_DIR / "ux_product_flow_specification.md").read_text()

    ia_text = "\n".join(f"- {item}" for item in o.get("information_architecture", [])) or "- None specified"

    def _render_screen(s: dict) -> str:
        return (
            f"### {s.get('id', '?')} — {s.get('name', 'Untitled')}\n"
            f"- **Purpose:** {s.get('purpose', 'N/A')}\n"
            f"- **Primary role:** {s.get('primary_role', 'N/A')}\n"
            f"- **Entry points:** {', '.join(s.get('entry_points', [])) or 'N/A'}\n"
            f"- **Exit points:** {', '.join(s.get('exit_points', [])) or 'N/A'}\n"
            f"- **Related stories:** {', '.join(s.get('related_story_ids', [])) or 'N/A'}\n"
            f"- **Related requirements:** {', '.join(s.get('related_requirement_ids', [])) or 'N/A'}\n"
            f"- **Primary actions:** {', '.join(s.get('primary_actions', [])) or 'N/A'}\n"
            f"- **Secondary actions:** {', '.join(s.get('secondary_actions', [])) or 'N/A'}\n"
            f"- **Navigation:** {s.get('navigation', 'N/A')}\n"
            f"- **Information displayed:** {', '.join(s.get('information_displayed', [])) or 'N/A'}\n"
            f"- **Data required:** {', '.join(s.get('data_required', [])) or 'N/A'}\n"
            f"- **UI elements required:** {', '.join(s.get('ui_elements_required', [])) or 'N/A'}\n"
            f"- **Permissions:** {s.get('permissions', 'N/A')}\n"
            f"- **Business rules:** {', '.join(s.get('business_rules', [])) or 'N/A'}\n"
            f"- **Dependencies:** {', '.join(s.get('dependencies', [])) or 'N/A'}\n"
        )
    screens_text = "\n".join(_render_screen(s) for s in o.get("screens", [])) or "None generated."

    def _render_flow(f: dict) -> str:
        main_path = "\n".join(f"    {i}. {step}" for i, step in enumerate(f.get("main_path", []), start=1))
        return (
            f"### {f.get('id', '?')} — {f.get('name', 'Untitled')}\n"
            f"- **Actor:** {f.get('actor', 'N/A')}\n"
            f"- **Goal:** {f.get('goal', 'N/A')}\n"
            f"- **Starting point:** {f.get('starting_point', 'N/A')}\n"
            f"- **Preconditions:** {f.get('preconditions', 'N/A')}\n"
            f"- **Main path:**\n{main_path}\n"
            f"- **Alternative paths:** {', '.join(f.get('alternative_paths', [])) or 'None'}\n"
            f"- **Error paths:** {', '.join(f.get('error_paths', [])) or 'None'}\n"
            f"- **Decision points:** {', '.join(f.get('decision_points', [])) or 'None'}\n"
            f"- **Completion state:** {f.get('completion_state', 'N/A')}\n"
            f"- **Related screens:** {', '.join(f.get('related_screen_ids', [])) or 'N/A'}\n"
            f"- **Related requirements:** {', '.join(f.get('related_requirement_ids', [])) or 'N/A'}\n"
            f"- **Related stories:** {', '.join(f.get('related_story_ids', [])) or 'N/A'}\n"
        )
    flows_text = "\n".join(_render_flow(f) for f in o.get("user_flows", [])) or "None generated."

    states_text = "\n".join(
        f"- **{s.get('screen_id', '?')}** [{s.get('state', '?')}]: sees \u201c{s.get('what_user_sees', '')}\u201d; "
        f"available: {', '.join(s.get('available_actions', [])) or 'none'}; "
        f"disabled: {', '.join(s.get('disabled_actions', [])) or 'none'}; next: {s.get('next_step', 'N/A')}"
        for s in o.get("screen_states", [])
    ) or "- None specified"

    interactions_text = "\n".join(
        f"- **{i.get('action', '?')}** — precondition: {i.get('preconditions', 'N/A')}; "
        f"behavior: {i.get('system_behavior', 'N/A')}; result: {i.get('user_visible_result', 'N/A')}; "
        f"next state: {i.get('next_state', 'N/A')}; possible errors: {', '.join(i.get('possible_errors', [])) or 'none'}"
        for i in o.get("interactions", [])
    ) or "- None specified"

    def _render_form(f: dict) -> str:
        rows = "\n".join(
            f"| {fld.get('field', '?')} | {fld.get('purpose', '')} | {fld.get('data_type', '')} | "
            f"{'Yes' if fld.get('required') else 'No'} | {fld.get('validation', '')} | {fld.get('default_value', 'None')} |"
            for fld in f.get("fields", [])
        )
        return (
            f"**{f.get('form_name', 'Untitled form')}** (Screen: {f.get('screen_id', 'N/A')})\n\n"
            f"| Field | Purpose | Type | Required | Validation | Default |\n|---|---|---|---|---|---|\n{rows}\n"
        )
    forms_text = "\n".join(_render_form(f) for f in o.get("forms", [])) or "None generated."

    nav = o.get("navigation", {})
    nav_text = _kv_block(nav)

    notif = o.get("notifications_and_feedback", {})
    notif_text = _kv_block(notif)

    matrix = o.get("roles_permissions_matrix", [])
    matrix_text = "\n".join(
        f"- **{r.get('role', '?')}:** " + (", ".join(r.get("permissions", [])) or "No permissions specified")
        for r in matrix
    ) or "None specified."

    responsive_text = _kv_block(o.get("responsive_requirements", {}))

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "information_architecture": ia_text,
        "screens": screens_text,
        "user_flows": flows_text,
        "screen_states": states_text,
        "interactions": interactions_text,
        "forms": forms_text,
        "navigation": nav_text,
        "notifications_and_feedback": notif_text,
        "roles_permissions_matrix": matrix_text,
        "responsive_requirements": responsive_text,
        "accessibility": o.get("accessibility", []),
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="ux_product_flow_specification",
                     title=f"UX Product Flow Specification — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.UX_PRODUCT_FLOW)


# ---------------------------------------------------------------------------
# 5. AI Handoff Validation
# ---------------------------------------------------------------------------

def export_ai_handoff_validation(context: ProjectContext) -> Artefact:
    val = context.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    o = val.output if val else {}
    template = (TEMPLATE_DIR / "ai_handoff_validation.md").read_text()

    conflicts = o.get("conflicts_found", [])
    conflicts_text = "\n".join(
        f"- **{c.get('id', '?')}** [{', '.join(c.get('documents_involved', []))}]: {c.get('conflicting_information', '')}\n"
        f"  - Impact: {c.get('impact', 'N/A')}\n  - Recommended resolution: {c.get('recommended_resolution', 'N/A')}"
        for c in conflicts
    ) or "- None found."

    missing = o.get("missing_information", [])
    missing_text = "\n".join(
        f"- **{m.get('missing_item', '?')}** (affects: {m.get('affected_document', 'N/A')})\n"
        f"  - Impact: {m.get('impact_on_design_generation', 'N/A')}\n  - Recommended action: {m.get('recommended_action', 'N/A')}"
        for m in missing
    ) or "- None found."

    totals = o.get("capability_summary", {})
    readiness_summary = (
        f"- **Total capabilities identified:** {totals.get('capabilities', 'N/A')}\n"
        f"- **Total Business Requirements:** {totals.get('business_requirements', 'N/A')}\n"
        f"- **Total PRD Functional Requirements:** {totals.get('prd_features', 'N/A')}\n"
        f"- **Total User Stories:** {totals.get('user_stories', 'N/A')}\n"
        f"- **Total UX Screens:** {totals.get('ux_screens', 'N/A')} / **UX Flows:** {totals.get('ux_flows', 'N/A')}\n"
        f"- **Deterministic coverage:** {totals.get('coverage_percentage', 'N/A')}%\n"
        f"- **Missing capabilities:** {len(o.get('missing_capabilities', []))}\n"
        f"- **Partial capabilities:** {len(o.get('partial_capabilities', []))}\n"
        f"- **Capabilities implied by the idea but unrepresented:** {len(o.get('unmapped_idea_capabilities', []))}"
    )

    matrix_rows = o.get("coverage_matrix", [])
    matrix_table = _table(
        ["Capability", "FR IDs", "BRD", "PRD", "User Story", "UX", "Technical", "Security", "Notes"],
        [[r.get("capability", ""), ", ".join(r.get("fr_ids", [])) or "—", r.get("brd", ""), r.get("prd", ""),
          r.get("user_story", ""), r.get("ux", ""), r.get("technical", ""), r.get("security", ""),
          "; ".join(r.get("notes", [])) or ""] for r in matrix_rows],
    )

    gap_caps = sorted(set(o.get("missing_capabilities", [])) | set(o.get("partial_capabilities", [])))
    gap_capabilities_text = _bullets(gap_caps) if gap_caps else "- None — every capability is fully covered."
    unmapped_text = _bullets(o.get("unmapped_idea_capabilities", [])) if o.get("unmapped_idea_capabilities") else "- None."

    fo = _feasibility_output(context)
    if fo:
        feasibility_check = (f"**Feasibility verdict: {fo.get('verdict', 'n/a')}** — {fo.get('verdict_rationale', '')}\n\n"
                             + ("**Flaws the specification must account for:**\n" + _bullets(fo.get("headline_flaws") or []) + "\n\n"
                                if fo.get("headline_flaws") else "")
                             + "*The verdict is advisory and does not change the handoff status above. See the Feasibility & Competitive Assessment for detail.*")
    else:
        feasibility_check = "*No feasibility assessment was run for this project.*"

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "feasibility_check": feasibility_check,
        "final_handoff_status": o.get("final_handoff_status", "UNKNOWN"),
        "recommendation": o.get("recommendation", "Not specified"),
        "readiness_summary": readiness_summary,
        "coverage_matrix_table": matrix_table,
        "gap_capabilities": gap_capabilities_text,
        "unmapped_idea_capabilities": unmapped_text,
        "completeness_notes": o.get("completeness_notes", []),
        "consistency_notes": o.get("consistency_notes", []),
        "design_readiness_notes": o.get("design_readiness_notes", []),
        "conflicts_found": conflicts_text,
        "missing_information": missing_text,
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="ai_handoff_validation",
                     title=f"AI Handoff Validation — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.AI_HANDOFF_VALIDATION)


# ---------------------------------------------------------------------------
# Orchestration of export
# ---------------------------------------------------------------------------

def export_all_artefacts(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "export", "started")

    artefacts = [
        export_feasibility_assessment(context),
        export_business_requirements(context),
        export_user_stories(context),
        export_prd(context),
        export_ux_product_flow(context),
        export_ai_handoff_validation(context),
    ]
    context.artefacts = artefacts
    # Exporting the 5 files is NOT what makes the package complete — a
    # document existing and a document being genuinely gap-free are
    # different things. Completion is decided solely by the AI Handoff
    # Validation agent's actual (deterministic-matrix-backed) verdict, set
    # by the orchestrator's gap-correction loop (see orchestrator.py). If
    # that loop hasn't run, or ran and still found real gaps, stage stays
    # at REVIEW — export never upgrades it to COMPLETE on its own.
    val = context.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    if val is not None:
        output = val.output
        matrix_gap = any(
            row.get(col) in ("⚠️ Partial", "❌ Missing")
            for row in output.get("coverage_matrix", [])
            for col in ("brd", "prd", "user_story", "ux", "technical", "security")
        ) or bool(output.get("unmapped_idea_capabilities"))
        is_clean = (
            output.get("final_handoff_status") == "READY FOR DESIGN AGENT"
            and not output.get("conflicts_found")
            and not output.get("missing_information")
            and not matrix_gap
        )
        context.stage = ProjectStage.COMPLETE if is_clean else ProjectStage.REVIEW
    else:
        context.stage = ProjectStage.REVIEW

    log_agent_call(logger, context.project_id, "export", "completed", {"count": len(artefacts), "stage": context.stage.value})
    return context


def save_artefacts_to_disk(context: ProjectContext, output_dir: str) -> list:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for a in context.artefacts:
        path = out / f"{a.type}.md"
        path.write_text(a.content_markdown)
        paths.append(str(path))
    return paths


if __name__ == "__main__":
    from context import DiscoveryQuestion
    from orchestrator import run_full_pipeline

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    summary = run_full_pipeline(ctx)
    ctx = export_all_artefacts(ctx)
    paths = save_artefacts_to_disk(ctx, "/tmp/poc_export_test")

    print(f"Stage: {ctx.stage.value}")
    print(f"Gap-correction summary: {summary}")
    print(f"Artefacts exported: {len(ctx.artefacts)}")
    for p in paths:
        print(f"  - {p}")

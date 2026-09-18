"""
Artefact Export — fills the 5 Markdown templates with agent outputs.
Deterministic — pure string substitution/formatting, no AI involved here.

Produces exactly 5 documents:
  business_requirements.md, user_stories.md, prd.md,
  ux_product_flow_specification.md, ai_handoff_validation.md
"""

import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import AgentRole, Artefact, ProjectContext, ProjectStage  # noqa: E402
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

    requirements = _table(["ID", "Requirement Name", "Description", "Primary Actor", "Priority"],
                           [[r.get("id", ""), r.get("name", ""), r.get("description", ""), r.get("actor") or r.get("module", ""), r.get("priority", "")] for r in o.get("requirements", [])])

    def _render_module_detail(m: dict) -> str:
        return (f"#### {m.get('module', '?')}\n"
                f"- **Purpose:** {m.get('purpose', 'N/A')}\n- **Actors:** {m.get('actors', 'N/A')}\n"
                f"- **Inputs:** {m.get('inputs', 'N/A')}\n- **Processing:** {m.get('processing', 'N/A')}\n"
                f"- **Outputs:** {m.get('outputs', 'N/A')}\n- **Business rules:** {m.get('business_rules', 'N/A')}\n"
                f"- **Dependencies:** {m.get('dependencies', 'N/A')}\n- **Priority:** {m.get('priority', 'N/A')}\n")
    module_details = "\n".join(_render_module_detail(m) for m in o.get("module_details", [])) or "*None specified.*"

    business_rules = _table(["Rule ID", "Business Rule"], [[b.get("id", ""), b.get("rule", "")] for b in o.get("business_rules", [])])

    nfrs = _table(["ID", "Category", "Requirement", "Priority"],
                   [[n.get("id", ""), n.get("category", ""), n.get("requirement", ""), n.get("priority", "")] for n in o.get("nfrs", [])])

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
        "future_state_flow": o.get("future_state_flow", "Not specified"),
        "user_journeys": user_journeys,
        "modules": modules,
        "requirements": requirements,
        "module_details": module_details,
        "business_rules": business_rules,
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
        "risks": _table(["Risk", "Impact", "Consequence", "Mitigation"],
                         [[r.get("risk", ""), r.get("impact", ""), r.get("consequence", ""), r.get("mitigation", "")] for r in o.get("risks", [])]),
        "mvp_prioritization": mvp_prioritization,
        "user_stories_summary": user_stories_summary,
        "acceptance_criteria_summary": acceptance_criteria_summary,
        "traceability_matrix": traceability_matrix,
        "release_strategy": release_strategy,
        "future_enhancements": o.get("future_enhancements", []),
        "glossary": glossary,
        "open_questions": o.get("open_questions", []),
    }
    content = _fill_template(template, values)
    return Artefact(id=str(uuid.uuid4()), type="business_requirements",
                     title=f"Business Requirements — {values['project_name']}",
                     content_markdown=content, generated_by=AgentRole.BUSINESS_ANALYST)


# ---------------------------------------------------------------------------
# 2. User Stories Document
# ---------------------------------------------------------------------------

def export_user_stories(context: ProjectContext) -> Artefact:
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    o = pm.output if pm else {}
    template = (TEMPLATE_DIR / "user_stories.md").read_text()

    epics_list = "\n".join(f"- **{e['id']}: {e['name']}** — {e['description']}" for e in o.get("epics", [])) or "- None generated"

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
        if s.get("business_rules"):
            lines.append("\n**Business rules:**")
            lines.extend(f"- {r}" for r in s["business_rules"])
        if s.get("acceptance_criteria"):
            lines.append("\n**Acceptance criteria:**")
            lines.extend(f"- {c}" for c in s["acceptance_criteria"])
        return "\n".join(lines) + "\n"

    stories_list = "\n".join(_render_story(s) for s in o.get("stories", [])) or "None generated"

    priority_rows = "\n".join(
        f"| {p['story_id']} | {p['priority']} | {p.get('notes', '')} |" for p in o.get("priorities", [])
    ) or "| - | - | - |"

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "epics_list": epics_list,
        "stories_list": stories_list,
        "priority_table_rows": priority_rows,
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

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "product_overview": o.get("product_overview", "Not specified"),
        "product_goals": o.get("product_goals", []),
        "target_users": o.get("target_users", "Not specified"),
        "personas": personas_text,
        "user_journeys": o.get("user_journeys", []),
        "product_capabilities": o.get("product_capabilities", []),
        "functional_requirements": fr_text,
        "roles_and_permissions": roles_text,
        "product_business_rules": o.get("product_business_rules", []),
        "navigation_behavior": o.get("navigation_behavior", "Not specified"),
        "notifications_and_confirmations": o.get("notifications_and_confirmations", []),
        "validation_and_error_handling": o.get("validation_and_error_handling", "Not specified"),
        "state_behaviors": _kv_block(o.get("state_behaviors", {})),
        "audit_and_versioning": o.get("audit_and_versioning", "Not specified"),
        "non_functional_requirements": o.get("non_functional_requirements", []),
        "technical_integration_constraints": _kv_block(o.get("technical_integration_constraints", {})),
        "security_privacy_access_constraints": _kv_block(o.get("security_privacy_access_constraints", {})),
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
    matrix_rows = "\n".join(
        f"| {r.get('role', '?')} | {'Yes' if r.get('view') else 'No'} | {'Yes' if r.get('edit') else 'No'} | "
        f"{'Yes' if r.get('approve') else 'No'} | {'Yes' if r.get('reject') else 'No'} |"
        for r in matrix
    )
    matrix_text = f"| Role | View | Edit | Approve | Reject |\n|---|---|---|---|---|\n{matrix_rows}" if matrix else "None specified."

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

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "final_handoff_status": o.get("final_handoff_status", "UNKNOWN"),
        "recommendation": o.get("recommendation", "Not specified"),
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
        export_business_requirements(context),
        export_user_stories(context),
        export_prd(context),
        export_ux_product_flow(context),
        export_ai_handoff_validation(context),
    ]
    context.artefacts = artefacts
    context.stage = ProjectStage.COMPLETE

    log_agent_call(logger, context.project_id, "export", "completed", {"count": len(artefacts)})
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
    from orchestrator import run_agent_pipeline

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    ctx = run_agent_pipeline(ctx)
    ctx = export_all_artefacts(ctx)
    paths = save_artefacts_to_disk(ctx, "/tmp/poc_export_test")

    print(f"Stage: {ctx.stage.value}")
    print(f"Artefacts exported: {len(ctx.artefacts)}")
    for p in paths:
        print(f"  - {p}")

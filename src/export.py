"""
Artefact Export — fills the 7 Markdown templates with agent outputs.
Deterministic — pure string substitution, no AI involved here.
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


def export_business_requirements(context: ProjectContext) -> Artefact:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    output = ba.output if ba else {}
    template = (TEMPLATE_DIR / "business_requirements.md").read_text()

    values = {
        "project_name": _project_name(context),
        "domain_classification": context.domain_classification or "Unclassified",
        "generated_date": _date(),
        "business_idea_summary": context.business_idea_raw,
        "target_users": output.get("target_users", "Not specified"),
        "stakeholders": output.get("stakeholders", []),
        "problem_statement": output.get("problem_statement", "Not specified"),
        "business_goals": output.get("business_goals", []),
        "success_metrics": output.get("success_metrics", []),
        "scope_in": output.get("scope_in", []),
        "scope_out": output.get("scope_out", []),
        "requirements_list": output.get("key_requirements", []),
        "constraints": output.get("constraints", []),
        "assumptions": output.get("assumptions", []),
        "open_questions": output.get("open_questions", []),
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="business_requirements",
        title=f"Business Requirements — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.BUSINESS_ANALYST,
    )


def export_user_stories(context: ProjectContext) -> Artefact:
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    output = pm.output if pm else {}
    template = (TEMPLATE_DIR / "user_stories.md").read_text()

    epics_list = "\n".join(
        f"- **{e['id']}: {e['name']}** — {e['description']}" for e in output.get("epics", [])
    ) or "- None generated"

    def _render_story(s: dict) -> str:
        base = f"- **{s['id']}** ({s.get('epic_id', '-')}): As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}."
        criteria = s.get("acceptance_criteria", [])
        if criteria:
            base += "\n  Acceptance criteria:\n" + "\n".join(f"    - {c}" for c in criteria)
        return base

    stories_list = "\n".join(_render_story(s) for s in output.get("stories", [])) or "- None generated"

    priority_rows = "\n".join(
        f"| {p['story_id']} | {p['priority']} | {p.get('notes', '')} |" for p in output.get("priorities", [])
    ) or "| - | - | - |"

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "epics_list": epics_list,
        "stories_list": stories_list,
        "priority_table_rows": priority_rows,
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="user_stories",
        title=f"User Stories — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.PRODUCT_MANAGER,
    )


def export_prd(context: ProjectContext) -> Artefact:
    prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    output = prd.output if prd else {}
    template = (TEMPLATE_DIR / "prd.md").read_text()

    milestones = "\n".join(
        f"- **{m.get('milestone', '?')}**: {m.get('description', '')}" for m in output.get("release_milestones", [])
    ) or "- None specified"

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "product_overview": output.get("product_overview", "Not specified"),
        "product_objectives": output.get("product_objectives", []),
        "functional_requirements": output.get("functional_requirements", []),
        "non_functional_requirements": output.get("non_functional_requirements", []),
        "success_metrics": output.get("success_metrics", []),
        "out_of_scope": output.get("out_of_scope", []),
        "release_milestones": milestones,
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="prd",
        title=f"PRD — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.PRODUCT_REQUIREMENTS,
    )


def export_architecture_recommendation(context: ProjectContext) -> Artefact:
    arch = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
    output = arch.output if arch else {}
    template = (TEMPLATE_DIR / "architecture_recommendation.md").read_text()

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "recommended_approach": output.get("recommended_approach", "Not specified"),
        "rationale": output.get("rationale", "Not specified"),
        "alternatives_considered": output.get("alternatives_considered", []),
        "key_components": output.get("key_components", []),
        "data_considerations": output.get("data_considerations", "Not specified"),
        "brief_security_note": output.get("brief_security_note", "See the Security Assessment document."),
        "scalability_notes": output.get("scalability_notes", "Not specified"),
        "risks_and_tradeoffs": output.get("risks_and_tradeoffs", []),
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="architecture_recommendation",
        title=f"Architecture — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.SOLUTION_ARCHITECT,
    )


def export_security_assessment(context: ProjectContext) -> Artefact:
    sec = context.get_contribution(AgentRole.SECURITY)
    output = sec.output if sec else {}
    template = (TEMPLATE_DIR / "security_assessment.md").read_text()

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "data_sensitivity_assessment": output.get("data_sensitivity_assessment", "Not specified"),
        "authentication_recommendations": output.get("authentication_recommendations", "Not specified"),
        "authorization_model": output.get("authorization_model", "Not specified"),
        "key_risks": output.get("key_risks", []),
        "compliance_considerations": output.get("compliance_considerations", []),
        "security_requirements": output.get("security_requirements", []),
        "mitigations": output.get("mitigations", []),
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="security_assessment",
        title=f"Security Assessment — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.SECURITY,
    )


def export_qa_test_strategy(context: ProjectContext) -> Artefact:
    qa = context.get_contribution(AgentRole.QA_TEST_STRATEGY)
    output = qa.output if qa else {}
    template = (TEMPLATE_DIR / "qa_test_strategy.md").read_text()

    def _render_case(tc: dict) -> str:
        steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(tc.get("steps", []), start=1))
        return (
            f"### {tc.get('id', '?')} — {tc.get('title', 'Untitled')}\n"
            f"*Related to: {tc.get('related_to', '—')}*\n\n"
            f"**Preconditions:** {tc.get('preconditions', 'None specified')}\n\n"
            f"**Steps:**\n{steps}\n\n"
            f"**Expected result:** {tc.get('expected_result', 'Not specified')}\n"
        )

    test_cases = output.get("test_cases", [])
    functional = [tc for tc in test_cases if tc.get("type") == "functional"]
    security = [tc for tc in test_cases if tc.get("type") != "functional"]

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "testing_scope": output.get("testing_scope", "Not specified"),
        "test_approach": output.get("test_approach", "Not specified"),
        "test_types": output.get("test_types", []),
        "test_environment": output.get("test_environment", "Not specified"),
        "entry_criteria": output.get("entry_criteria", []),
        "exit_criteria": output.get("exit_criteria", []),
        "functional_test_cases": "\n".join(_render_case(tc) for tc in functional) or "None generated.",
        "security_test_cases": "\n".join(_render_case(tc) for tc in security) or "None generated.",
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="qa_test_strategy",
        title=f"QA Test Strategy — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.QA_TEST_STRATEGY,
    )


def export_ai_review_report(context: ProjectContext) -> Artefact:
    qa = context.get_contribution(AgentRole.QA_REVIEWER)
    output = qa.output if qa else {}
    template = (TEMPLATE_DIR / "ai_review_report.md").read_text()

    conflicts = output.get("conflicts_found", [])
    conflicts_text = "\n".join(
        f"- **[{c.get('between_agents', '?')}]** {c.get('description', '')}" for c in conflicts
    ) or "- None found."

    values = {
        "project_name": _project_name(context),
        "generated_date": _date(),
        "overall_readiness": (output.get("overall_readiness", "unknown")).upper(),
        "recommendation": output.get("recommendation", "Not specified"),
        "consistency_notes": output.get("consistency_notes", []),
        "conflicts_found": conflicts_text,
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="ai_review_report",
        title=f"AI Review Report — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.QA_REVIEWER,
    )


def export_all_artefacts(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "export", "started")

    artefacts = [
        export_business_requirements(context),
        export_user_stories(context),
        export_prd(context),
        export_architecture_recommendation(context),
        export_security_assessment(context),
        export_qa_test_strategy(context),
        export_ai_review_report(context),
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

    print("\n--- Preview: business_requirements.md ---\n")
    print(ctx.artefacts[0].content_markdown[:600])

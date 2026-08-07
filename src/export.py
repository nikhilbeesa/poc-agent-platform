"""
Artefact Export
================
Takes a completed ProjectContext (discovery answered + all 5 agents run)
and fills the Markdown templates in artefact_templates/ with the actual
agent outputs, producing the Phase 1 deliverables named in the spec:
business requirements, user stories, and architecture recommendation.

Deterministic — pure string substitution, no AI involved here. All the
reasoning already happened in the agents; this only formats it.
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
    # Anything left unfilled gets an honest placeholder rather than silently vanishing
    text = re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "Not specified", text)
    return text


def export_business_requirements(context: ProjectContext) -> Artefact:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    output = ba.output if ba else {}
    template = (TEMPLATE_DIR / "business_requirements.md").read_text()

    values = {
        "project_name": (context.business_idea_raw[:60] or "Untitled Project"),
        "domain_classification": context.domain_classification or "Unclassified",
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "business_idea_summary": context.business_idea_raw,
        "target_users": output.get("target_users", "Not specified"),
        "problem_statement": output.get("problem_statement", "Not specified"),
        "business_goals": output.get("business_goals", []),
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

    stories_list = "\n".join(
        f"- **{s['id']}** ({s.get('epic_id', '-')}): As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}."
        for s in output.get("stories", [])
    ) or "- None generated"

    priority_rows = "\n".join(
        f"| {p['story_id']} | {p['priority']} | {p.get('notes', '')} |" for p in output.get("priorities", [])
    ) or "| - | - | - |"

    values = {
        "project_name": (context.business_idea_raw[:60] or "Untitled Project"),
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
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


def export_architecture_recommendation(context: ProjectContext) -> Artefact:
    arch = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
    sec = context.get_contribution(AgentRole.SECURITY)
    arch_output = arch.output if arch else {}
    sec_output = sec.output if sec else {}
    template = (TEMPLATE_DIR / "architecture_recommendation.md").read_text()

    # Combine the architect's own security note with the dedicated
    # Security agent's review, so the artefact reflects both perspectives.
    security_section = arch_output.get("security_considerations", "Not specified")
    if sec_output:
        security_section += "\n\n**Security agent review:**\n"
        security_section += f"- Data sensitivity: {sec_output.get('data_sensitivity_assessment', 'N/A')}\n"
        security_section += f"- Authentication: {sec_output.get('authentication_recommendations', 'N/A')}\n"
        security_section += "- Key risks:\n" + "\n".join(f"  - {r}" for r in sec_output.get("key_risks", []))
        security_section += "\n- Mitigations:\n" + "\n".join(f"  - {m}" for m in sec_output.get("mitigations", []))

    values = {
        "project_name": (context.business_idea_raw[:60] or "Untitled Project"),
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "recommended_approach": arch_output.get("recommended_approach", "Not specified"),
        "rationale": arch_output.get("rationale", "Not specified"),
        "alternatives_considered": arch_output.get("alternatives_considered", []),
        "key_components": arch_output.get("key_components", []),
        "data_considerations": arch_output.get("data_considerations", "Not specified"),
        "security_considerations": security_section,
        "scalability_notes": arch_output.get("scalability_notes", "Not specified"),
        "risks_and_tradeoffs": arch_output.get("risks_and_tradeoffs", []),
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="architecture_recommendation",
        title=f"Architecture Recommendation — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.SOLUTION_ARCHITECT,
    )


def export_test_cases(context: ProjectContext) -> Artefact:
    qa = context.get_contribution(AgentRole.QA_REVIEWER)
    output = qa.output if qa else {}
    template = (TEMPLATE_DIR / "test_cases.md").read_text()

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
        "project_name": (context.business_idea_raw[:60] or "Untitled Project"),
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "functional_test_cases": "\n".join(_render_case(tc) for tc in functional) or "None generated.",
        "security_test_cases": "\n".join(_render_case(tc) for tc in security) or "None generated.",
    }
    content = _fill_template(template, values)
    return Artefact(
        id=str(uuid.uuid4()), type="test_cases",
        title=f"Test Cases — {values['project_name']}",
        content_markdown=content, generated_by=AgentRole.QA_REVIEWER,
    )


def export_all_artefacts(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "export", "started")

    artefacts = [
        export_business_requirements(context),
        export_user_stories(context),
        export_architecture_recommendation(context),
        export_test_cases(context),
    ]
    context.artefacts = artefacts
    context.stage = ProjectStage.COMPLETE

    log_agent_call(logger, context.project_id, "export", "completed", {"count": len(artefacts)})
    return context


def save_artefacts_to_disk(context: ProjectContext, output_dir: str) -> list[str]:
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
        DiscoveryQuestion(id="q1", text="Who books?", category="users",
                           status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments",
                           status="answered", answer="At time of booking"),
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

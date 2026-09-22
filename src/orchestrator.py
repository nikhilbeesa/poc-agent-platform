"""
Orchestrator — sequences the 5 agents. Deterministic, no AI reasoning here.

  Business Analyst        -> no dependency, runs first
  Product Manager           -> reads Business Analyst
  Product Requirements       -> reads Business Analyst + Product Manager
  UX / Product Flow            -> reads Product Manager + Product Requirements
  AI Handoff Validation           -> reads everyone, runs last
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.business_analyst import BusinessAnalystAgent  # noqa: E402
from agents.product_manager import ProductManagerAgent  # noqa: E402
from agents.product_requirements import ProductRequirementsAgent  # noqa: E402
from agents.ux_product_flow import UXProductFlowAgent  # noqa: E402
from agents.ai_handoff_validation import AIHandoffValidationAgent  # noqa: E402
from context import AgentRole, ProjectContext, ProjectStage  # noqa: E402
from discovery import is_discovery_complete  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()

AGENT_PIPELINE = [
    BusinessAnalystAgent(),
    ProductManagerAgent(),
    ProductRequirementsAgent(),
    UXProductFlowAgent(),
    AIHandoffValidationAgent(),
]

# Pipeline order for the 4 content-generating agents (excludes validation,
# which always runs last and isn't itself a re-run target). Used both to
# decide which agents to re-run during conflict resolution and to cascade
# forward to anything downstream of a fixed document.
CONTENT_PIPELINE_ORDER = [
    AgentRole.BUSINESS_ANALYST,
    AgentRole.PRODUCT_MANAGER,
    AgentRole.PRODUCT_REQUIREMENTS,
    AgentRole.UX_PRODUCT_FLOW,
]

_AGENT_BY_ROLE = {
    AgentRole.BUSINESS_ANALYST: AGENT_PIPELINE[0],
    AgentRole.PRODUCT_MANAGER: AGENT_PIPELINE[1],
    AgentRole.PRODUCT_REQUIREMENTS: AGENT_PIPELINE[2],
    AgentRole.UX_PRODUCT_FLOW: AGENT_PIPELINE[3],
}

# Keyword sets used to map a free-text document name (as written by the
# validation agent — which may say "Business Requirements Document", "BRD",
# "PRD", "Product Requirements", "UX/Product Flow Specification", etc.,
# since the LLM isn't constrained to the exact artefact type strings) back
# to the agent role that owns that document. Checked most-specific-first
# so e.g. "Product Requirements" doesn't get mistaken for "Business
# Requirements" just because both contain "requirements".
_DOCUMENT_NAME_KEYWORDS = [
    (AgentRole.UX_PRODUCT_FLOW, ("ux", "flow", "screen", "wireframe", "interaction")),
    (AgentRole.PRODUCT_REQUIREMENTS, ("prd", "product requirement")),
    (AgentRole.PRODUCT_MANAGER, ("user stor", "stories", "epic")),
    (AgentRole.BUSINESS_ANALYST, ("business", "brd")),
]


def _map_document_name_to_role(name: str):
    normalized = (name or "").lower()
    for role, keywords in _DOCUMENT_NAME_KEYWORDS:
        if any(k in normalized for k in keywords):
            return role
    return None


def run_agent_pipeline(context: ProjectContext, require_discovery_complete: bool = True) -> ProjectContext:
    if require_discovery_complete and not is_discovery_complete(context):
        raise ValueError("Discovery is not complete — all discovery questions must be answered before running the agent pipeline.")

    context.stage = ProjectStage.AGENT_PROCESSING
    log_agent_call(logger, context.project_id, "orchestrator", "started", {"pipeline": [a.role.value for a in AGENT_PIPELINE]})

    for agent in AGENT_PIPELINE:
        agent.run(context)

    context.stage = ProjectStage.REVIEW
    log_agent_call(logger, context.project_id, "orchestrator", "completed", {"contributions": len(context.agent_contributions)})
    return context


def resolve_handoff_issues(context: ProjectContext) -> dict:
    """Re-runs exactly the agent(s) implicated by the latest AI Handoff
    Validation's flagged conflicts/missing-information — plus anything
    downstream of them in the pipeline, since a fix upstream can change
    what downstream documents should say — then re-validates.

    Returns a small summary dict describing what was done, so the caller
    (the API layer) can tell the user what changed. Does nothing and
    returns {"resolved": False, "reason": ...} if there's no validation
    contribution yet or it found nothing to fix.
    """
    validation = context.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    if not validation:
        return {"resolved": False, "reason": "The agent pipeline hasn't been run yet — nothing to resolve."}

    conflicts = validation.output.get("conflicts_found", [])
    missing = validation.output.get("missing_information", [])
    if not conflicts and not missing:
        return {"resolved": False, "reason": "No conflicts or missing information were flagged — nothing to resolve."}

    notes = []
    targeted_roles = set()
    unattributed = False
    for c in conflicts:
        notes.append(f"{c.get('id', 'CONFLICT')}: {c.get('conflicting_information', '')} Recommended fix: {c.get('recommended_resolution', '')}".strip())
        docs = c.get("documents_involved", [])
        matched = [r for r in (_map_document_name_to_role(d) for d in docs) if r]
        if matched:
            targeted_roles.update(matched)
        else:
            unattributed = True
    for m in missing:
        notes.append(f"Missing: {m.get('missing_item', '')} (affects {m.get('affected_document', '')}). Recommended action: {m.get('recommended_action', '')}".strip())
        role = _map_document_name_to_role(m.get("affected_document", ""))
        if role:
            targeted_roles.add(role)
        else:
            unattributed = True

    # If any issue couldn't be attributed to a specific document, or none
    # were, the safe default is to re-run the whole content pipeline
    # rather than risk leaving a real problem untouched.
    if unattributed or not targeted_roles:
        roles_to_rerun = list(CONTENT_PIPELINE_ORDER)
    else:
        earliest_idx = min(CONTENT_PIPELINE_ORDER.index(r) for r in targeted_roles)
        roles_to_rerun = CONTENT_PIPELINE_ORDER[earliest_idx:]

    log_agent_call(logger, context.project_id, "orchestrator", "resolving_issues",
                    {"conflicts": len(conflicts), "missing": len(missing), "rerunning": [r.value for r in roles_to_rerun]})

    context.resolution_notes = notes
    for role in roles_to_rerun:
        _AGENT_BY_ROLE[role].run(context)
    context.resolution_notes = []

    new_validation = AIHandoffValidationAgent().run(context)

    return {
        "resolved": True,
        "agents_rerun": [r.value for r in roles_to_rerun],
        "issues_addressed": len(notes),
        "new_status": new_validation.output.get("final_handoff_status"),
        "new_conflicts_count": len(new_validation.output.get("conflicts_found", [])),
        "new_missing_count": len(new_validation.output.get("missing_information", [])),
    }


if __name__ == "__main__":
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners, mostly recurring"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    ctx = run_agent_pipeline(ctx)
    print(f"\nStage: {ctx.stage.value}")
    print(f"Contributions: {len(ctx.agent_contributions)}")
    for c in ctx.agent_contributions:
        print(f"[{c.agent.value}] {c.summary}")

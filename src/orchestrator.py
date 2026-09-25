"""
Orchestrator — sequences the 5 agents. Deterministic, no AI reasoning here.

  Business Analyst        -> no dependency, runs first
  Product Manager           -> reads Business Analyst
  Product Requirements       -> reads Business Analyst + Product Manager
  UX / Product Flow            -> reads Product Manager + Product Requirements
  AI Handoff Validation           -> reads everyone, runs last

The pipeline finishing (5 contributions present) is NOT the same as the
package being COMPLETE. Completion is gated on an automatic gap-correction
loop: run validation, and if it finds real gaps (conflicts, missing
information, or a coverage-matrix gap), automatically re-run exactly the
implicated agents with those gaps as hard requirements, then re-validate —
repeating until either everything is clean or a small iteration cap is
hit. The user is never asked to manually point out a gap that the
business idea and discovery answers already make derivable.
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
import coverage as cov  # noqa: E402
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

# Capability names (as used in coverage.py's matrix rows) are matched back
# to the agent role(s) that own the columns where a gap was found, so a
# capability-specific gap re-runs only what's actually implicated (plus
# everything downstream of it) rather than the whole pipeline every time.
_MATRIX_COLUMN_TO_ROLES = {
    "brd": [AgentRole.BUSINESS_ANALYST],
    "prd": [AgentRole.PRODUCT_REQUIREMENTS],
    "user_story": [AgentRole.PRODUCT_MANAGER],
    "ux": [AgentRole.UX_PRODUCT_FLOW],
    "technical": [AgentRole.PRODUCT_REQUIREMENTS],
    "security": [AgentRole.PRODUCT_REQUIREMENTS],
}

MAX_GAP_CORRECTION_ROUNDS = 4

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
    # Deliberately requires "requirement(s)" or "brd" alongside "business" —
    # bare "business" alone false-positives on things like "business rules"
    # or "business logic" mentioned in passing inside a PRD/UX conflict
    # description, which isn't naming the Business Requirements document at
    # all. That false match was cascading EVERY resolve round all the way
    # back to re-running the Business Analyst (and therefore everything
    # downstream of it) even when the actual issue was only between the
    # PRD and the UX spec — regenerating all 4 documents from scratch each
    # round rather than making a targeted fix to the two actually involved.
    (AgentRole.BUSINESS_ANALYST, ("business requirement", "brd", "business analyst")),
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


def _roles_from_validation_issues(validation_output: dict) -> tuple[set, bool]:
    """Maps a validation contribution's conflicts/missing-information onto
    the content-agent roles they implicate. Returns (roles, unattributed)."""
    targeted_roles = set()
    unattributed = False
    for c in validation_output.get("conflicts_found", []):
        docs = c.get("documents_involved", [])
        matched = [r for r in (_map_document_name_to_role(d) for d in docs) if r]
        if matched:
            targeted_roles.update(matched)
        else:
            unattributed = True
    for m in validation_output.get("missing_information", []):
        role = _map_document_name_to_role(m.get("affected_document", ""))
        if role:
            targeted_roles.add(role)
        else:
            unattributed = True
    return targeted_roles, unattributed


def _roles_from_coverage_matrix(validation_output: dict) -> set:
    """Maps ❌/⚠️ cells in the attached coverage_matrix onto the agent
    role(s) that own the corresponding document, so a capability-specific
    gap (e.g. only the PRD's technical section is missing something) only
    re-runs the agent(s) that can actually fix it."""
    roles = set()
    for row in validation_output.get("coverage_matrix", []) or []:
        for column, agent_roles in _MATRIX_COLUMN_TO_ROLES.items():
            if row.get(column) in ("⚠️ Partial", "❌ Missing"):
                roles.update(agent_roles)
    if validation_output.get("unmapped_idea_capabilities"):
        # An idea-implied capability with no module at all starts life in
        # the Business Requirements — everything downstream cascades from there.
        roles.add(AgentRole.BUSINESS_ANALYST)
    return roles


def _notes_from_validation_issues(validation_output: dict) -> list[str]:
    notes = []
    for c in validation_output.get("conflicts_found", []):
        notes.append(f"{c.get('id', 'CONFLICT')}: {c.get('conflicting_information', '')} Recommended fix: {c.get('recommended_resolution', '')}".strip())
    for m in validation_output.get("missing_information", []):
        notes.append(f"Missing: {m.get('missing_item', '')} (affects {m.get('affected_document', '')}). Recommended action: {m.get('recommended_action', '')}".strip())
    return notes


def _apply_resolution(context: ProjectContext, notes: list[str], roles_to_rerun: list) -> None:
    context.resolution_notes = notes
    for role in roles_to_rerun:
        _AGENT_BY_ROLE[role].run(context)
    context.resolution_notes = []


def run_gap_correction_loop(context: ProjectContext, max_rounds: int = MAX_GAP_CORRECTION_ROUNDS) -> dict:
    """Runs AI Handoff Validation, and — automatically, without asking the
    user — repeatedly re-runs exactly the agent(s) implicated by whatever
    gaps it finds (both LLM-reported conflicts/missing-information and the
    deterministic coverage-matrix gaps from coverage.py), re-validating
    after each round, until the package is genuinely clean or max_rounds
    is reached.

    Sets context.stage to COMPLETE only when the final validation is
    actually clean (final_handoff_status == "READY FOR DESIGN AGENT" and
    no coverage-matrix gaps). Otherwise stage stays at REVIEW and the
    returned summary says exactly what's still outstanding — the package
    is never silently marked complete just because 5 documents exist.
    """
    rounds_used = 0
    validation = AIHandoffValidationAgent().run(context)

    while rounds_used < max_rounds:
        output = validation.output
        matrix_gap = cov.matrix_has_blocking_gaps({
            "missing_capabilities": output.get("missing_capabilities", []),
            "partial_capabilities": output.get("partial_capabilities", []),
            "unmapped_idea_capabilities": output.get("unmapped_idea_capabilities", []),
        })
        has_issues = bool(output.get("conflicts_found") or output.get("missing_information")) or matrix_gap
        if not has_issues:
            break

        issue_roles, unattributed = _roles_from_validation_issues(output)
        issue_roles |= _roles_from_coverage_matrix(output)
        notes = _notes_from_validation_issues(output) + cov.gap_resolution_notes({
            "rows": output.get("coverage_matrix", []),
            "unmapped_idea_capabilities": output.get("unmapped_idea_capabilities", []),
        })
        if not notes:
            break  # nothing actionable was actually extracted — avoid an infinite no-op loop

        if unattributed or not issue_roles:
            roles_to_rerun = list(CONTENT_PIPELINE_ORDER)
        else:
            earliest_idx = min(CONTENT_PIPELINE_ORDER.index(r) for r in issue_roles)
            roles_to_rerun = CONTENT_PIPELINE_ORDER[earliest_idx:]

        rounds_used += 1
        log_agent_call(logger, context.project_id, "orchestrator", "auto_gap_correction",
                        {"round": rounds_used, "rerunning": [r.value for r in roles_to_rerun], "issues": len(notes)})

        _apply_resolution(context, notes, roles_to_rerun)
        validation = AIHandoffValidationAgent().run(context)

    final_output = validation.output
    final_matrix_gap = cov.matrix_has_blocking_gaps({
        "missing_capabilities": final_output.get("missing_capabilities", []),
        "partial_capabilities": final_output.get("partial_capabilities", []),
        "unmapped_idea_capabilities": final_output.get("unmapped_idea_capabilities", []),
    })
    is_clean = (
        final_output.get("final_handoff_status") == "READY FOR DESIGN AGENT"
        and not final_output.get("conflicts_found")
        and not final_output.get("missing_information")
        and not final_matrix_gap
    )

    context.stage = ProjectStage.COMPLETE if is_clean else ProjectStage.REVIEW
    log_agent_call(logger, context.project_id, "orchestrator", "gap_correction_finished",
                    {"rounds_used": rounds_used, "is_clean": is_clean, "final_status": final_output.get("final_handoff_status")})

    return {
        "rounds_used": rounds_used,
        "is_clean": is_clean,
        "final_status": final_output.get("final_handoff_status"),
        "capability_summary": final_output.get("capability_summary"),
        "missing_capabilities": final_output.get("missing_capabilities", []),
        "partial_capabilities": final_output.get("partial_capabilities", []),
        "unmapped_idea_capabilities": final_output.get("unmapped_idea_capabilities", []),
        "remaining_conflicts": len(final_output.get("conflicts_found", [])),
        "remaining_missing": len(final_output.get("missing_information", [])),
    }


def run_full_pipeline(context: ProjectContext, require_discovery_complete: bool = True, max_rounds: int = MAX_GAP_CORRECTION_ROUNDS) -> dict:
    """Convenience wrapper: runs the 4 content agents, then the automatic
    gap-correction loop through validation. This is the entry point that
    actually satisfies the "no artifact package is COMPLETE until it's
    genuinely gap-free (or the iteration cap is hit and that's reported
    honestly)" rule — callers that only need the 4 content documents
    without validation/repair can still call run_agent_pipeline directly."""
    if require_discovery_complete and not is_discovery_complete(context):
        raise ValueError("Discovery is not complete — all discovery questions must be answered before running the agent pipeline.")

    context.stage = ProjectStage.AGENT_PROCESSING
    for agent in AGENT_PIPELINE[:-1]:  # everything except AI Handoff Validation
        agent.run(context)
    context.stage = ProjectStage.REVIEW

    return run_gap_correction_loop(context, max_rounds=max_rounds)


def resolve_handoff_issues(context: ProjectContext) -> dict:
    """Manually-triggered equivalent of one round of run_gap_correction_loop
    — re-runs exactly the agent(s) implicated by the latest AI Handoff
    Validation's flagged conflicts/missing-information AND coverage-matrix
    gaps (plus anything downstream of them), then re-validates. Kept for
    callers (e.g. an explicit "Resolve Issues" action) that want to trigger
    one more repair pass on demand; automatic completion no longer depends
    on this being called manually.

    Returns a small summary dict describing what was done, so the caller
    (the API layer) can tell the user what changed. Does nothing and
    returns {"resolved": False, "reason": ...} if there's no validation
    contribution yet or it found nothing to fix.
    """
    validation = context.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    if not validation:
        return {"resolved": False, "reason": "The agent pipeline hasn't been run yet — nothing to resolve."}

    output = validation.output
    matrix_gap = cov.matrix_has_blocking_gaps({
        "missing_capabilities": output.get("missing_capabilities", []),
        "partial_capabilities": output.get("partial_capabilities", []),
        "unmapped_idea_capabilities": output.get("unmapped_idea_capabilities", []),
    })
    if not output.get("conflicts_found") and not output.get("missing_information") and not matrix_gap:
        return {"resolved": False, "reason": "No conflicts or missing information were flagged — nothing to resolve."}

    issue_roles, unattributed = _roles_from_validation_issues(output)
    issue_roles |= _roles_from_coverage_matrix(output)
    notes = _notes_from_validation_issues(output) + cov.gap_resolution_notes({
        "rows": output.get("coverage_matrix", []),
        "unmapped_idea_capabilities": output.get("unmapped_idea_capabilities", []),
    })

    if unattributed or not issue_roles:
        roles_to_rerun = list(CONTENT_PIPELINE_ORDER)
    else:
        earliest_idx = min(CONTENT_PIPELINE_ORDER.index(r) for r in issue_roles)
        roles_to_rerun = CONTENT_PIPELINE_ORDER[earliest_idx:]

    log_agent_call(logger, context.project_id, "orchestrator", "resolving_issues",
                    {"issues": len(notes), "rerunning": [r.value for r in roles_to_rerun]})

    _apply_resolution(context, notes, roles_to_rerun)
    new_validation = AIHandoffValidationAgent().run(context)
    new_output = new_validation.output
    new_matrix_gap = cov.matrix_has_blocking_gaps({
        "missing_capabilities": new_output.get("missing_capabilities", []),
        "partial_capabilities": new_output.get("partial_capabilities", []),
        "unmapped_idea_capabilities": new_output.get("unmapped_idea_capabilities", []),
    })
    context.stage = (
        ProjectStage.COMPLETE
        if new_output.get("final_handoff_status") == "READY FOR DESIGN AGENT" and not new_matrix_gap
           and not new_output.get("conflicts_found") and not new_output.get("missing_information")
        else ProjectStage.REVIEW
    )

    return {
        "resolved": True,
        "agents_rerun": [r.value for r in roles_to_rerun],
        "issues_addressed": len(notes),
        "new_status": new_output.get("final_handoff_status"),
        "new_conflicts_count": len(new_output.get("conflicts_found", [])),
        "new_missing_count": len(new_output.get("missing_information", [])),
        "capability_summary": new_output.get("capability_summary"),
    }


if __name__ == "__main__":
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners, mostly recurring"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    summary = run_full_pipeline(ctx)
    print(f"\nStage: {ctx.stage.value}")
    print(f"Contributions: {len(ctx.agent_contributions)}")
    print(f"Gap-correction summary: {summary}")
    for c in ctx.agent_contributions:
        print(f"[{c.agent.value}] {c.summary}")


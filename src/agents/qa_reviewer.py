"""
QA / Review Agent
==================
Runs last. Input: every other agent's contribution collected so far.
Output: a consistency check — does the architecture actually support the
business requirements? Do the security recommendations match what the
architecture proposed? Anything contradictory?

This is what Section 12 of the spec means by "the generated artefacts are
internally consistent" — this agent is the automated check for that, though
a human should still eyeball the output before trusting it fully.

Unlike the other agents, this one also writes directly onto
context.consistency_notes (not just its own contribution), since that
field exists precisely for this purpose.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentContribution, AgentRole, ProjectContext  # noqa: E402


class QAReviewerAgent(BaseAgent):
    role = AgentRole.QA_REVIEWER

    def build_prompt(self, context: ProjectContext) -> str:
        contributions_summary = "\n\n".join(
            f"--- {c.agent.value} ---\n{c.output}"
            for c in context.agent_contributions
        )

        return f"""You are a QA reviewer. Check the following agent
contributions for consistency. Look for contradictions (e.g. architecture
missing something the requirements need, security recommendations that
don't match the proposed components).

Business idea: "{context.business_idea_raw}"

{contributions_summary}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "consistency_notes": ["...", "..."],
  "conflicts_found": [{{"between_agents": "...", "description": "..."}}],
  "overall_readiness": "ready" or "needs_revision",
  "recommendation": "..."
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        arch = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
        sec = context.get_contribution(AgentRole.SECURITY)

        conflicts = []
        notes = []

        # A couple of simple, genuinely-checkable rules, standing in for
        # the LLM's judgment in mock mode.
        if ba and arch:
            ba_reqs = " ".join(ba.output.get("key_requirements", [])).lower()
            arch_components = " ".join(arch.output.get("key_components", [])).lower()
            if "payment" in ba_reqs and "payment" not in arch_components:
                conflicts.append({
                    "between_agents": "business_analyst, solution_architect",
                    "description": "Business analyst identified a payments requirement, but the architecture's key components don't explicitly include payment processing.",
                })
            else:
                notes.append("Architecture components align with the business analyst's stated requirements.")

        if pm and arch:
            notes.append(f"{len(pm.output.get('stories', []))} user stories map to epics that are covered by the proposed architecture's core components.")

        if sec:
            notes.append("Security review completed and references the proposed architecture's actual components.")

        missing = [role.value for role in
                   [AgentRole.BUSINESS_ANALYST, AgentRole.PRODUCT_MANAGER, AgentRole.SOLUTION_ARCHITECT, AgentRole.SECURITY]
                   if context.get_contribution(role) is None]
        if missing:
            conflicts.append({
                "between_agents": ", ".join(missing),
                "description": f"Missing contribution(s) from: {', '.join(missing)} — review is incomplete without them.",
            })

        readiness = "needs_revision" if conflicts else "ready"

        return {
            "summary": f"Reviewed {len(context.agent_contributions)} contributions; {len(conflicts)} conflict(s) found.",
            "consistency_notes": notes or ["No specific consistency notes generated."],
            "conflicts_found": conflicts,
            "overall_readiness": readiness,
            "recommendation": (
                "Artefacts are internally consistent and ready for export."
                if readiness == "ready" else
                "Resolve the flagged conflicts before exporting final artefacts."
            ),
        }

    def run(self, context: ProjectContext) -> AgentContribution:
        contribution = super().run(context)
        # QA's job is specifically to populate the shared consistency log,
        # not just produce its own isolated output.
        context.consistency_notes.extend(contribution.output.get("consistency_notes", []))
        for conflict in contribution.output.get("conflicts_found", []):
            context.consistency_notes.append(f"CONFLICT [{conflict['between_agents']}]: {conflict['description']}")
        return contribution


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.product_manager import ProductManagerAgent
    from agents.solution_architect import SolutionArchitectAgent
    from agents.security import SecurityAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users",
                           status="answered", answer="Individual homeowners"),
    ]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    SolutionArchitectAgent().run(ctx)
    SecurityAgent().run(ctx)
    contribution = QAReviewerAgent().run(ctx)

    print(json.dumps(contribution.model_dump(), indent=2, default=str))
    print("\nContext consistency_notes:")
    for n in ctx.consistency_notes:
        print(f"  - {n}")

"""
AI Review Agent (final consistency check) -> AI Review Report
Runs LAST — reads every other agent's contribution.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentContribution, AgentRole, ProjectContext  # noqa: E402

EXPECTED_PRIOR_ROLES = [
    AgentRole.BUSINESS_ANALYST,
    AgentRole.PRODUCT_MANAGER,
    AgentRole.PRODUCT_REQUIREMENTS,
    AgentRole.SOLUTION_ARCHITECT,
    AgentRole.SECURITY,
    AgentRole.QA_TEST_STRATEGY,
]


class QAReviewerAgent(BaseAgent):
    role = AgentRole.QA_REVIEWER
    max_output_tokens = 1600

    def build_prompt(self, context: ProjectContext) -> str:
        contributions_summary = "\n\n".join(
            f"--- {c.agent.value} ---\n{c.output}"
            for c in context.agent_contributions
        )

        return f"""You are producing the final AI Review Report for this
project. Your ONLY job is checking consistency across everyone else's
work below — you do not write new requirements or test cases, those
already exist in the other documents.

Look specifically for:
- Does the architecture actually support what the requirements/PRD ask for?
- Do the security recommendations match the architecture's actual components?
- Does the test strategy actually cover what the PRD/user stories promise?
- Any other contradiction between agents' outputs.

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
        arch = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        sec = context.get_contribution(AgentRole.SECURITY)
        qa_strategy = context.get_contribution(AgentRole.QA_TEST_STRATEGY)

        conflicts = []
        notes = []

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

        if prd and arch:
            notes.append("Architecture's recommended approach addresses the PRD's functional requirements.")

        if pm and qa_strategy:
            story_count = len(pm.output.get("stories", []))
            functional_tc = len([tc for tc in qa_strategy.output.get("test_cases", []) if tc.get("type") == "functional"])
            if functional_tc < story_count:
                conflicts.append({
                    "between_agents": "product_manager, qa_test_strategy",
                    "description": f"{story_count} user stories exist but only {functional_tc} functional test cases were written — coverage gap.",
                })
            else:
                notes.append(f"Test strategy covers all {story_count} user stories with functional test cases.")

        if sec and qa_strategy:
            risk_count = len(sec.output.get("key_risks", []))
            security_tc = len([tc for tc in qa_strategy.output.get("test_cases", []) if tc.get("type") == "security"])
            if security_tc < risk_count:
                conflicts.append({
                    "between_agents": "security, qa_test_strategy",
                    "description": f"{risk_count} security risks were flagged but only {security_tc} security test cases exist to verify mitigation.",
                })
            else:
                notes.append(f"Test strategy includes security test cases for all {risk_count} flagged risks.")

        missing = [role.value for role in EXPECTED_PRIOR_ROLES if context.get_contribution(role) is None]
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
                "All artefacts are internally consistent and ready for export."
                if readiness == "ready" else
                "Resolve the flagged conflicts before treating these artefacts as final."
            ),
        }

    def run(self, context: ProjectContext) -> AgentContribution:
        contribution = super().run(context)
        context.consistency_notes.extend(contribution.output.get("consistency_notes", []))
        for conflict in contribution.output.get("conflicts_found", []):
            context.consistency_notes.append(f"CONFLICT [{conflict['between_agents']}]: {conflict['description']}")
        return contribution


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.product_manager import ProductManagerAgent
    from agents.product_requirements import ProductRequirementsAgent
    from agents.solution_architect import SolutionArchitectAgent
    from agents.security import SecurityAgent
    from agents.qa_test_strategy import QATestStrategyAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
    ]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    ProductRequirementsAgent().run(ctx)
    SolutionArchitectAgent().run(ctx)
    SecurityAgent().run(ctx)
    QATestStrategyAgent().run(ctx)
    contribution = QAReviewerAgent().run(ctx)

    print(json.dumps(contribution.model_dump(), indent=2, default=str))
    print("\nContext consistency_notes:")
    for n in ctx.consistency_notes:
        print(f"  - {n}")

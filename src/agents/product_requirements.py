"""
Product Requirements Agent -> Product Requirements Document (PRD)
Reads Business Analyst + Product Manager; runs after both.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class ProductRequirementsAgent(BaseAgent):
    role = AgentRole.PRODUCT_REQUIREMENTS
    max_output_tokens = 2000

    def build_prompt(self, context: ProjectContext) -> str:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        epic_names = [e.get("name") for e in pm_output.get("epics", [])]

        return f"""You are a product manager writing a formal Product
Requirements Document (PRD). Synthesize the business analysis and the
epics/stories below into a proper PRD — this is a different document from
the user stories list, aimed at giving anyone (including non-technical
stakeholders) a clear picture of what's being built and why.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Problem: {ba_output.get('problem_statement', 'N/A')}
- Target users: {ba_output.get('target_users', 'N/A')}
- Business goals: {ba_output.get('business_goals', [])}
- Success metrics: {ba_output.get('success_metrics', [])}
- In scope: {ba_output.get('scope_in', [])}
- Out of scope: {ba_output.get('scope_out', [])}

Product manager's epics: {epic_names}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "product_overview": "a clear paragraph describing the product",
  "product_objectives": ["...", "... — specific, ideally measurable objectives"],
  "functional_requirements": ["...", "... — what the system must DO"],
  "non_functional_requirements": ["...", "... — performance, reliability, usability, etc."],
  "success_metrics": ["...", "..."],
  "out_of_scope": ["...", "..."],
  "release_milestones": [{{"milestone": "...", "description": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        domain = (context.domain_classification or "general_business").replace("_", " ")
        epics = pm_output.get("epics", [])

        return {
            "summary": f"PRD synthesizing the business case and {len(epics)} epics for the {domain} idea.",
            "product_overview": f"{context.business_idea_raw}. This product addresses: {ba_output.get('problem_statement', 'the described problem')}",
            "product_objectives": ba_output.get("business_goals", ["Deliver core value to target users"]),
            "functional_requirements": [
                f"System must support: {e.get('description', e.get('name', 'a core capability'))}" for e in epics
            ] or ["System must support the core workflow described in the idea"],
            "non_functional_requirements": [
                "System should respond to user actions within 2 seconds under normal load",
                "System should be usable on both desktop and mobile browsers",
                "System should log key actions for auditability",
            ],
            "success_metrics": ba_output.get("success_metrics", ["User adoption within first 90 days"]),
            "out_of_scope": ba_output.get("scope_out", ["Advanced analytics/reporting (future phase)"]),
            "release_milestones": [
                {"milestone": "MVP", "description": f"Core {domain} workflow live for early users"},
                {"milestone": "V1", "description": "Full feature set from the epics above, hardened for broader release"},
            ],
        }


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.product_manager import ProductManagerAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
    ]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    contribution = ProductRequirementsAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

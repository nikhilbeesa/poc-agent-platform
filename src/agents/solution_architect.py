"""
Solution Architect Agent -> Solution Architecture Recommendation
Reads Business Analyst + Product Requirements.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class SolutionArchitectAgent(BaseAgent):
    role = AgentRole.SOLUTION_ARCHITECT
    max_output_tokens = 1600

    def build_prompt(self, context: ProjectContext) -> str:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        prd_contribution = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        ba_output = ba_contribution.output if ba_contribution else {}
        prd_output = prd_contribution.output if prd_contribution else {}

        return f"""You are a solution architect. Based on the business
analysis and product requirements below, recommend a technical approach.
Recommend — do not assume a single fixed stack; note the reasoning and
alternatives considered. A dedicated Security agent will produce the full
security assessment separately, so keep your own security note brief —
just flag anything architecturally relevant.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Problem: {ba_output.get('problem_statement', 'N/A')}
- Target users: {ba_output.get('target_users', 'N/A')}
- Key requirements: {ba_output.get('key_requirements', [])}
- Constraints: {ba_output.get('constraints', [])}

Product requirements:
- Functional requirements: {prd_output.get('functional_requirements', [])}
- Non-functional requirements: {prd_output.get('non_functional_requirements', [])}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "recommended_approach": "...",
  "rationale": "...",
  "alternatives_considered": ["...", "..."],
  "key_components": ["...", "..."],
  "data_considerations": "...",
  "brief_security_note": "one or two sentences flagging anything architecturally relevant to security — full assessment is a separate document",
  "scalability_notes": "...",
  "risks_and_tradeoffs": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}
        domain = context.domain_classification or "general_business"
        requirements = ba_output.get("key_requirements", [])

        return {
            "summary": f"Recommends a modular web-first architecture for the {domain.replace('_', ' ')} idea, informed by {len(requirements)} identified requirements.",
            "recommended_approach": "A modular web application with a REST or similar API layer between front end and back end, deployable incrementally as a POC and scalable later.",
            "rationale": f"Matches the requirements surfaced by the business analyst ({', '.join(requirements[:2]) if requirements else 'core workflow support'}) without over-committing to infrastructure the POC doesn't need yet.",
            "alternatives_considered": [
                "Fully serverless architecture — deferred until usage patterns are clearer",
                "No-code/low-code platform — faster for POC but harder to extend later",
            ],
            "key_components": [
                "User-facing web/app client",
                "API layer",
                "Core data store",
                "Authentication",
            ] + (["Payment processing"] if any("payment" in r.lower() for r in requirements) else []),
            "data_considerations": "Start with a relational data model unless the domain has clear document/graph needs; revisit as real usage data comes in.",
            "brief_security_note": "Standard authentication and data-at-rest protection expected — see the Security Assessment document for the full review.",
            "scalability_notes": "POC scope only — architecture should avoid decisions that would require a full rewrite to scale, without over-building for scale that isn't validated yet.",
            "risks_and_tradeoffs": [
                "Choosing flexibility over speed may slow the POC timeline",
                "Recommendation is based on assumed constraints where discovery answers were incomplete",
            ],
        }


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.product_manager import ProductManagerAgent
    from agents.product_requirements import ProductRequirementsAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    ProductRequirementsAgent().run(ctx)
    contribution = SolutionArchitectAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

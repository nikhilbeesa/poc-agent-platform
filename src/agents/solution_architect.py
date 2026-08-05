"""
Solution Architect Agent
=========================
Input: the raw idea, domain, and — importantly — the Business Analyst's
contribution (requirements, constraints, target users). This is the first
real "handoff" in the pipeline: one agent's output becomes another agent's
input, both going through the shared ProjectContext rather than talking
directly to each other.

Output maps onto artefact_templates/architecture_recommendation.md.

Per the spec's guiding principle ("recommend, don't assume"), this agent
proposes AN approach with reasoning and alternatives — it does not lock in
a fixed tech stack.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class SolutionArchitectAgent(BaseAgent):
    role = AgentRole.SOLUTION_ARCHITECT

    def build_prompt(self, context: ProjectContext) -> str:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}

        return f"""You are a solution architect. Based on the business
analysis below, recommend a technical approach. Recommend — do not assume
a single fixed stack; note the reasoning and alternatives considered.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Problem: {ba_output.get('problem_statement', 'N/A')}
- Target users: {ba_output.get('target_users', 'N/A')}
- Key requirements: {ba_output.get('key_requirements', [])}
- Constraints: {ba_output.get('constraints', [])}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "recommended_approach": "...",
  "rationale": "...",
  "alternatives_considered": ["...", "..."],
  "key_components": ["...", "..."],
  "data_considerations": "...",
  "security_considerations": "...",
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
            "security_considerations": ba_output.get(
                "constraints", ["Standard authentication and data protection practices apply"]
            )[0] if ba_output.get("constraints") else "Standard authentication and data-at-rest protection for a POC.",
            "scalability_notes": "POC scope only — architecture should avoid decisions that would require a full rewrite to scale, without over-building for scale that isn't validated yet.",
            "risks_and_tradeoffs": [
                "Choosing flexibility over speed may slow the POC timeline",
                "Recommendation is based on assumed constraints where discovery answers were incomplete",
            ],
        }


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users",
                           status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments",
                           status="answered", answer="At time of booking"),
    ]

    BusinessAnalystAgent().run(ctx)  # run BA first so Architect can read it
    contribution = SolutionArchitectAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

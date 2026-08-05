"""
Product Manager Agent
======================
Input: the idea, domain, and the Business Analyst's contribution
(requirements, goals, target users).
Output: epics and user stories with prioritisation — maps directly onto
artefact_templates/user_stories.md.

Runs after Business Analyst, before Solution Architect — the architecture
should be informed by what's actually being asked for, not the other way
around.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class ProductManagerAgent(BaseAgent):
    role = AgentRole.PRODUCT_MANAGER

    def build_prompt(self, context: ProjectContext) -> str:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}

        return f"""You are a product manager. Based on the business analysis
below, break the work into epics and user stories with priorities.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Target users: {ba_output.get('target_users', 'N/A')}
- Business goals: {ba_output.get('business_goals', [])}
- Key requirements: {ba_output.get('key_requirements', [])}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "epics": [{{"id": "E1", "name": "...", "description": "..."}}],
  "stories": [{{"id": "S1", "epic_id": "E1", "as_a": "...", "i_want": "...", "so_that": "..."}}],
  "priorities": [{{"story_id": "S1", "priority": "High|Medium|Low", "notes": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}
        requirements = ba_output.get("key_requirements", []) or ["Core workflow support"]
        target_users = ba_output.get("target_users", "end users")

        epics = [
            {"id": "E1", "name": "Core workflow", "description": f"Support the primary flow described in the business idea for {target_users}."},
            {"id": "E2", "name": "Onboarding", "description": "Get new users set up and able to use the platform."},
        ]

        stories = []
        for i, req in enumerate(requirements[:3], start=1):
            stories.append({
                "id": f"S{i}",
                "epic_id": "E1",
                "as_a": target_users,
                "i_want": req[0].lower() + req[1:] if req else "to complete the core workflow",
                "so_that": "I can get value from the platform quickly",
            })
        stories.append({
            "id": f"S{len(stories) + 1}",
            "epic_id": "E2",
            "as_a": target_users,
            "i_want": "to sign up and get started easily",
            "so_that": "I don't abandon the platform before using it",
        })

        priorities = [
            {"story_id": s["id"], "priority": "High" if s["epic_id"] == "E1" else "Medium",
             "notes": "Core to the value proposition" if s["epic_id"] == "E1" else "Needed but not the differentiator"}
            for s in stories
        ]

        return {
            "summary": f"Broke the idea into {len(epics)} epics and {len(stories)} user stories, prioritised around the core workflow.",
            "epics": epics,
            "stories": stories,
            "priorities": priorities,
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
    ]

    BusinessAnalystAgent().run(ctx)
    contribution = ProductManagerAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

"""
Product Manager Agent -> User Stories Document
Answers: "Who needs to do what, and why?"
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class ProductManagerAgent(BaseAgent):
    role = AgentRole.PRODUCT_MANAGER
    max_output_tokens = 2400

    def build_prompt(self, context: ProjectContext) -> str:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}
        requirements = ba_output.get("requirements", [])

        return f"""You are a product manager. Based on the business
requirements below, produce detailed, behaviorally rich user stories —
this document will be read by other AI agents downstream to derive
product flows and screens, so short statements like "As a user, I want X
so that Y" are NOT enough. Include real behavioral detail: preconditions,
triggers, main/alternative/exception flows, and Given/When/Then
acceptance criteria.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Target users: {ba_output.get('target_users', 'N/A')}
- Personas: {ba_output.get('user_personas', [])}
- Business goals: {ba_output.get('business_goals', [])}
- Requirements: {requirements}
- In scope: {ba_output.get('scope_in', [])}
- Business rules: {ba_output.get('business_rules', [])}

Rules:
- Assign each story a unique ID: US-001, US-002, ...
- Assign each epic a unique ID: EPIC-001, EPIC-002, ...
- Reference which BR-XXX requirement(s) each story relates to.
- Use Given/When/Then for acceptance criteria where appropriate.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "epics": [{{"id": "EPIC-001", "name": "...", "description": "..."}}],
  "stories": [{{
    "id": "US-001", "epic_id": "EPIC-001", "feature": "...",
    "role": "user role/persona",
    "story": "As a [role], I want [goal], so that [benefit]",
    "business_value": "...",
    "preconditions": "...",
    "trigger": "...",
    "main_flow": ["step 1", "step 2", "..."],
    "alternative_flow": "... or 'None'",
    "exception_flow": "... or 'None'",
    "business_rules": ["...", "..."],
    "dependencies": ["...", "..."],
    "acceptance_criteria": ["Given ..., when ..., then ...", "..."],
    "related_br_ids": ["BR-001"]
  }}],
  "priorities": [{{"story_id": "US-001", "priority": "High|Medium|Low", "notes": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_output = ba_contribution.output if ba_contribution else {}
        requirements = ba_output.get("requirements", []) or [{"id": "BR-001", "text": "Core workflow support"}]
        target_users = ba_output.get("target_users", "end users")

        epics = [
            {"id": "EPIC-001", "name": "Core workflow", "description": f"Support the primary flow described in the business idea for {target_users}."},
            {"id": "EPIC-002", "name": "Onboarding", "description": "Get new users set up and able to use the platform."},
        ]

        stories = []
        for i, req in enumerate(requirements[:3], start=1):
            req_text = req.get("text", "complete the core workflow") if isinstance(req, dict) else str(req)
            req_id = req.get("id", f"BR-{i:03d}") if isinstance(req, dict) else f"BR-{i:03d}"
            want = req_text[0].lower() + req_text[1:] if req_text else "complete the core workflow"
            sid = f"US-{i:03d}"
            stories.append({
                "id": sid, "epic_id": "EPIC-001", "feature": req_text, "role": target_users,
                "story": f"As a {target_users}, I want to {want}, so that I can get value from the platform quickly.",
                "business_value": "Directly delivers on a core business requirement.",
                "preconditions": f"User has a valid, authenticated account matching role: {target_users}",
                "trigger": f"User initiates the action to {want}",
                "main_flow": ["User navigates to the relevant screen", f"User performs the action to {want}", "System confirms the action completed successfully"],
                "alternative_flow": "None",
                "exception_flow": "System displays a clear error if the action cannot be completed and preserves user input where possible",
                "business_rules": ["Only authenticated users may perform this action"],
                "dependencies": [],
                "acceptance_criteria": [
                    f"Given a valid {target_users} account, when the user attempts to {want}, then the action completes without errors",
                    "Given the action completes, when the system responds, then the user receives explicit confirmation",
                ],
                "related_br_ids": [req_id],
            })

        onboarding_id = f"US-{len(stories) + 1:03d}"
        stories.append({
            "id": onboarding_id, "epic_id": "EPIC-002", "feature": "Onboarding", "role": target_users,
            "story": f"As a {target_users}, I want to sign up and get started easily, so that I don't abandon the platform before using it.",
            "business_value": "Reduces drop-off before first use, directly affecting adoption metrics.",
            "preconditions": "User does not yet have an account",
            "trigger": "User visits the platform for the first time",
            "main_flow": ["User provides required sign-up information", "System validates and creates the account", "User lands on a clear next-step screen"],
            "alternative_flow": "None",
            "exception_flow": "System shows a clear validation error and allows the user to correct input",
            "business_rules": ["Sign-up requires a valid, unique identifier (e.g. email)"],
            "dependencies": [],
            "acceptance_criteria": [
                "Given a new visitor, when they complete sign-up with valid information, then an account is created in under 2 minutes",
                "Given sign-up completes, when the user is redirected, then they land on a clear next-step screen",
            ],
            "related_br_ids": ["BR-002"],
        })

        priorities = [
            {"story_id": s["id"], "priority": "High" if s["epic_id"] == "EPIC-001" else "Medium",
             "notes": "Core to the value proposition" if s["epic_id"] == "EPIC-001" else "Needed but not the differentiator"}
            for s in stories
        ]

        return {
            "summary": f"Broke the idea into {len(epics)} epics and {len(stories)} user stories, prioritised around the core workflow.",
            "epics": epics, "stories": stories, "priorities": priorities,
        }


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners")]
    BusinessAnalystAgent().run(ctx)
    contribution = ProductManagerAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

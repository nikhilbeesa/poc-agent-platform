"""
Product Manager Agent -> User Stories Document
Answers: "What are we building, story by story?"

Converts every functional requirement identified for this project's
module set into a fully detailed user story (Given/When/Then acceptance
criteria, main/alternative/exception flow, business rules), grouped into
epics — one epic per product module — rather than a handful of samples.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402
import content_kit as ck  # noqa: E402


class ProductManagerAgent(BaseAgent):
    role = AgentRole.PRODUCT_MANAGER
    max_output_tokens = 8000

    def build_prompt(self, context: ProjectContext) -> str:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        ba_out = ba.output if ba else {}
        requirements = ba_out.get("requirements", [])
        req_text = "\n".join(f"- {r.get('id')}: {r.get('name')} — {r.get('description')} (actor: {r.get('actor')}, priority: {r.get('priority')})" for r in requirements)
        modules_text = "\n".join(f"- {m.get('id')}: {m.get('name')} — {m.get('purpose')}" for m in ba_out.get("modules", []))
        return f"""{self.resolution_notes_block(context)}You are a senior product manager converting a full set
of business requirements into a comprehensive, detailed user story
backlog — the kind of document that runs dozens of pages, not 3 sample
stories. Every functional requirement below must become its own user
story; do not sample or truncate the list.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Product modules (use these as epics, one epic per module):
{modules_text}

Functional requirements to convert into user stories (EVERY one needs a
story — there is no cap on how many):
{req_text}

For each user story include: a unique ID (US-001, US-002, ...), the epic
it belongs to, the actor/role, a "As a ___, I want ___, so that ___"
story statement, the business value, preconditions, trigger, a numbered
main flow, alternative flow, exception flow, the relevant business
rule(s), 2+ Given/When/Then acceptance criteria, and a "dependencies"
list of the story IDs that must be completed first (e.g. almost every
story outside the authentication epic depends on the login/registration
story, since its own preconditions require an authenticated actor —
leave the list empty only if the story genuinely has no prerequisite).
Also produce a priority table (High/Medium/Low with a short note) for
every story, tied to the originating requirement's priority (P0/P1 ->
High, P2 -> Medium, P3 -> Low).

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "epics": [{{"id": "EPIC-001", "name": "...", "description": "..."}}],
  "stories": [{{
    "id": "US-001", "epic_id": "EPIC-001", "feature": "...", "role": "...",
    "story": "As a ..., I want ..., so that ...", "business_value": "...",
    "preconditions": "...", "trigger": "...",
    "main_flow": ["...", "..."], "alternative_flow": "...", "exception_flow": "...",
    "business_rules": ["..."], "dependencies": [],
    "acceptance_criteria": ["Given ..., when ..., then ...", "..."],
    "related_fr_ids": ["FR-001"]
  }}],
  "priorities": [{{"story_id": "US-001", "priority": "High|Medium|Low", "notes": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        modules = ck.select_modules(context)
        requirements = ck.build_functional_requirements(modules)
        epics = ck.build_epics(modules)
        stories = ck.build_stories(requirements, modules, context)
        priorities = ck.build_priorities(stories, requirements)

        return {
            "summary": f"Converted {len(requirements)} functional requirements across {len(epics)} epics into {len(stories)} fully detailed user stories.",
            "epics": epics,
            "stories": stories,
            "priorities": priorities,
        }


if __name__ == "__main__":
    import json
    from context import DiscoveryQuestion
    from agents.business_analyst import BusinessAnalystAgent

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
    ]
    BusinessAnalystAgent().run(ctx)
    contribution = ProductManagerAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

"""
Business Analyst Agent
=======================
Input: the raw idea, domain classification, and answered discovery questions.
Output: a structured business analysis — problem statement, target users,
goals, requirements, constraints, assumptions, open questions.

This maps directly onto artefact_templates/business_requirements.md —
Phase 5 will take this output and drop it straight into that template.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class BusinessAnalystAgent(BaseAgent):
    role = AgentRole.BUSINESS_ANALYST

    def build_prompt(self, context: ProjectContext) -> str:
        answered = "\n".join(
            f"- {q.text} -> {q.answer}"
            for q in context.discovery_questions if q.answer
        )
        return f"""You are a business analyst. Analyse this business idea and
produce a structured requirements summary.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Answered discovery questions:
{answered}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "problem_statement": "...",
  "target_users": "...",
  "business_goals": ["...", "..."],
  "key_requirements": ["...", "..."],
  "constraints": ["...", "..."],
  "assumptions": ["...", "..."],
  "open_questions": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        answers = {q.id: q.answer for q in context.discovery_questions if q.answer}
        domain = context.domain_classification or "general_business"

        return {
            "summary": f"Business analysis for a {domain.replace('_', ' ')} idea based on {len(answers)} answered questions.",
            "problem_statement": f"Users need a better way to accomplish the goal described in: \"{context.business_idea_raw}\"",
            "target_users": next(iter(answers.values()), "Not yet specified — no discovery answers available."),
            "business_goals": [
                "Validate the core value proposition with early users",
                "Reach initial operational viability",
            ],
            "key_requirements": [
                f"Support the core workflow for a {domain.replace('_', ' ')}",
                "Provide a simple onboarding flow",
                "Support secure payments" if "payment" in " ".join(str(v) for v in answers.values()).lower() else "Core browsing/discovery experience",
            ],
            "constraints": [
                "POC scope — not production scale",
                "Limited initial budget/timeline (assumed for POC)",
            ],
            "assumptions": [
                "Users have internet-connected devices",
                "Initial launch targets a single geography",
            ],
            "open_questions": [
                q.text for q in context.discovery_questions if q.status.value == "pending"
            ] or ["None outstanding — all discovery questions were answered"],
        }


if __name__ == "__main__":
    import json
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users",
                           status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments",
                           status="answered", answer="At time of booking"),
    ]

    agent = BusinessAnalystAgent()
    contribution = agent.run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

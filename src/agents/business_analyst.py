"""
Business Analyst Agent -> Business Requirements Document
Answers: "Why are we building this product?"
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class BusinessAnalystAgent(BaseAgent):
    role = AgentRole.BUSINESS_ANALYST
    max_output_tokens = 2200

    def build_prompt(self, context: ProjectContext) -> str:
        answered = "\n".join(f"- {q.text} -> {q.answer}" for q in context.discovery_questions if q.answer)
        return f"""You are a business analyst producing a detailed Business
Requirements Document (BRD). This document will be read by other AI agents
downstream (not just humans), so it must be specific, structured, and
self-contained.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Answered discovery questions:
{answered}

Rules:
- Assign each major requirement a unique ID: BR-001, BR-002, BR-003, ...
- Do not invent unsupported business information.
- If something is unknown, explicitly mark it as an assumption, TBD, or
  open question rather than guessing at a specific answer.
- Requirements must be specific and meaningful, not generic boilerplate.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "project_overview": "a clear paragraph describing the product",
  "problem_statement": "a detailed paragraph on the problem being solved",
  "target_users": "detailed description of who this is for",
  "user_personas": [{{"name": "...", "role": "...", "goals": "...", "pain_points": "..."}}],
  "stakeholders": ["...", "..."],
  "user_pain_points": ["...", "..."],
  "business_objectives": ["...", "..."],
  "business_goals": ["...", "..."],
  "expected_business_outcomes": ["...", "..."],
  "success_metrics": ["...", "..."],
  "scope_in": ["...", "..."],
  "scope_out": ["...", "..."],
  "requirements": [{{"id": "BR-001", "text": "...", "category": "..."}}],
  "business_rules": ["...", "..."],
  "constraints": ["...", "..."],
  "assumptions": ["...", "..."],
  "dependencies": ["...", "..."],
  "risks": ["...", "..."],
  "open_questions": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        answers = {q.id: q.answer for q in context.discovery_questions if q.answer}
        domain = context.domain_classification or "general_business"
        domain_readable = domain.replace("_", " ")
        target_users = next(iter(answers.values()), "Not yet specified — no discovery answers available.")

        requirements = [
            {"id": "BR-001", "text": f"Support the core workflow for a {domain_readable}", "category": "functional"},
            {"id": "BR-002", "text": "Provide a simple onboarding flow", "category": "functional"},
            {"id": "BR-003", "text": (
                "Support secure payments" if "payment" in " ".join(str(v) for v in answers.values()).lower()
                else "Provide a core browsing/discovery experience"
            ), "category": "functional"},
        ]

        return {
            "summary": f"Business analysis for a {domain_readable} idea based on {len(answers)} answered questions.",
            "project_overview": f"{context.business_idea_raw}",
            "problem_statement": f"Users need a better way to accomplish the goal described in: \"{context.business_idea_raw}\"",
            "target_users": target_users,
            "user_personas": [
                {"name": "Primary User", "role": target_users, "goals": "Accomplish the core workflow quickly and reliably", "pain_points": "Currently lacks a dedicated, simple way to do this"},
            ],
            "stakeholders": [
                "End users interacting with the platform directly",
                "Operations team responsible for day-to-day running",
                "Business sponsor/owner accountable for outcomes",
            ],
            "user_pain_points": [
                "No single dedicated tool exists for this workflow today",
                "Manual/ad-hoc processes are slow and error-prone",
            ],
            "business_objectives": ["Validate the core value proposition with early users", "Reach initial operational viability"],
            "business_goals": ["Validate the core value proposition with early users", "Reach initial operational viability"],
            "expected_business_outcomes": [
                "Increased efficiency for the target user in the core workflow",
                "A validated foundation to expand feature scope in later phases",
            ],
            "success_metrics": [
                "Number of completed core-workflow transactions in the first 90 days",
                "User retention rate after first use",
            ],
            "scope_in": [f"Core {domain_readable} workflow as described in the idea", "Basic user onboarding"],
            "scope_out": ["Advanced analytics/reporting (future phase)", "Multi-region/multi-currency support (future phase)"],
            "requirements": requirements,
            "business_rules": ["Only authenticated users may perform the core workflow action"],
            "constraints": ["POC scope — not production scale", "Limited initial budget/timeline (assumed for POC)"],
            "assumptions": ["ASSUMPTION: Users have internet-connected devices", "ASSUMPTION: Initial launch targets a single geography"],
            "dependencies": ["TBD: Third-party integrations, if any, not yet identified from discovery"],
            "risks": ["Low initial adoption if onboarding friction is too high"],
            "open_questions": [q.text for q in context.discovery_questions if q.status.value == "pending"] or ["None outstanding — all discovery questions were answered"],
        }


if __name__ == "__main__":
    import json
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]
    contribution = BusinessAnalystAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

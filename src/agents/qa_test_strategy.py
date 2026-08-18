"""
QA Test Strategy Agent -> QA/Test Strategy document
Reads Product Manager + Security. Distinct from the final AI Review Report.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class QATestStrategyAgent(BaseAgent):
    role = AgentRole.QA_TEST_STRATEGY
    max_output_tokens = 2200

    def build_prompt(self, context: ProjectContext) -> str:
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        sec = context.get_contribution(AgentRole.SECURITY)
        pm_output = pm.output if pm else {}
        sec_output = sec.output if sec else {}

        return f"""You are a QA lead writing a Test Strategy document for
this project. Cover the strategy-level decisions AND produce concrete
test cases — don't stop at an arbitrary count, write as many as genuinely
needed for real coverage.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

User stories to cover: {pm_output.get('stories', [])}
Security risks to cover: {sec_output.get('key_risks', [])}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "testing_scope": "what will and won't be tested, and why",
  "test_approach": "overall approach — manual/automated mix, testing pyramid, etc.",
  "test_types": ["functional", "security", "... — the types of testing this project needs"],
  "test_environment": "what environment/setup is needed to run these tests",
  "entry_criteria": ["...", "... — what must be true before testing can start"],
  "exit_criteria": ["...", "... — what must be true to consider testing done"],
  "test_cases": [
    {{
      "id": "TC1",
      "type": "functional or security or edge_case",
      "related_to": "story id or risk this test verifies, e.g. S1",
      "title": "short test name",
      "preconditions": "...",
      "steps": ["...", "..."],
      "expected_result": "..."
    }}
  ]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        sec = context.get_contribution(AgentRole.SECURITY)
        pm_output = pm.output if pm else {}
        sec_output = sec.output if sec else {}

        test_cases = self._mock_test_cases(pm_output, sec_output)

        return {
            "summary": f"Test strategy covering {len(pm_output.get('stories', []))} user stories and {len(sec_output.get('key_risks', []))} security risks, with {len(test_cases)} test case(s).",
            "testing_scope": "Functional coverage of every user story, plus security tests for every risk flagged by the security review. Performance/load testing out of scope for this POC stage.",
            "test_approach": "Manual exploratory testing for the POC, with test cases written so they're straightforward to automate later as the project matures.",
            "test_types": ["functional", "security", "edge_case"],
            "test_environment": "A staging environment matching production configuration, with test data that doesn't include real user/payment information.",
            "entry_criteria": [
                "All user stories have been implemented and deployed to staging",
                "Security mitigations from the Security Assessment are in place",
            ],
            "exit_criteria": [
                "All functional test cases pass",
                "All security test cases confirm mitigations actually work, not just documented",
                "No open critical/high severity defects",
            ],
            "test_cases": test_cases,
        }

    def _mock_test_cases(self, pm_output: dict, sec_output: dict) -> list[dict]:
        cases = []
        n = 0

        for story in pm_output.get("stories", []):
            n += 1
            cases.append({
                "id": f"TC{n}",
                "type": "functional",
                "related_to": story.get("id", "?"),
                "title": f"Verify: {story.get('i_want', 'core action')}",
                "preconditions": f"User is acting as: {story.get('as_a', 'a user')}",
                "steps": [
                    f"Set up a user matching '{story.get('as_a', 'the target user')}'",
                    f"Attempt to {story.get('i_want', 'perform the described action')}",
                ],
                "expected_result": f"User successfully achieves: {story.get('so_that', 'the intended benefit')}",
            })

        for risk in sec_output.get("key_risks", []):
            n += 1
            cases.append({
                "id": f"TC{n}",
                "type": "security",
                "related_to": "security review",
                "title": f"Verify mitigation for: {risk}",
                "preconditions": "System deployed with proposed security mitigations in place",
                "steps": [
                    f"Attempt to trigger the risk scenario: {risk}",
                    "Observe whether the system's mitigation actually prevents/limits it",
                ],
                "expected_result": "The risk is mitigated or blocked, not just documented",
            })

        return cases


if __name__ == "__main__":
    import json
    from agents.product_manager import ProductManagerAgent
    from agents.business_analyst import BusinessAnalystAgent
    from agents.solution_architect import SolutionArchitectAgent
    from agents.security import SecurityAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners"),
    ]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    SolutionArchitectAgent().run(ctx)
    SecurityAgent().run(ctx)
    contribution = QATestStrategyAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

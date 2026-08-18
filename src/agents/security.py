"""
Security Agent -> Security Assessment (dedicated document)
Reads Business Analyst + Solution Architect.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class SecurityAgent(BaseAgent):
    role = AgentRole.SECURITY
    max_output_tokens = 1800

    def build_prompt(self, context: ProjectContext) -> str:
        ba_contribution = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        arch_contribution = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
        ba_output = ba_contribution.output if ba_contribution else {}
        arch_output = arch_contribution.output if arch_contribution else {}

        return f"""You are a security reviewer producing a full Security
Assessment document (not just a brief note). Be concrete and specific to
this project, not generic boilerplate.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business constraints: {ba_output.get('constraints', [])}
Target users: {ba_output.get('target_users', 'N/A')}

Proposed architecture: {arch_output.get('recommended_approach', 'N/A')}
Key components: {arch_output.get('key_components', [])}
Data considerations: {arch_output.get('data_considerations', 'N/A')}

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "data_sensitivity_assessment": "...",
  "authentication_recommendations": "...",
  "authorization_model": "... — how different user roles/permissions should be structured",
  "key_risks": ["...", "..."],
  "compliance_considerations": ["...", "..."],
  "security_requirements": ["...", "... — concrete requirements the dev team must implement, not just principles"],
  "mitigations": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        arch_contribution = context.get_contribution(AgentRole.SOLUTION_ARCHITECT)
        arch_output = arch_contribution.output if arch_contribution else {}
        components = arch_output.get("key_components", [])
        has_payments = any("payment" in c.lower() for c in components)

        return {
            "summary": f"Security review flags {'payment handling and ' if has_payments else ''}standard authentication/data-protection needs for the proposed architecture.",
            "data_sensitivity_assessment": (
                "Handles payment and personal data — treat as sensitive"
                if has_payments else
                "Handles personal/account data — moderate sensitivity, standard protections apply"
            ),
            "authentication_recommendations": "Use a standard managed auth provider rather than building auth in-house for the POC; enforce MFA for any admin/provider accounts.",
            "authorization_model": "Role-based access control with at minimum: customer, provider/vendor, and admin roles, each scoped to only the data/actions they need.",
            "key_risks": [
                "Payment data exposure if handled directly rather than via a processor" if has_payments else "Account takeover via weak authentication",
                "Insufficient access controls between user roles (e.g. customer vs. provider vs. admin)",
            ],
            "compliance_considerations": [
                "PCI-DSS scope reduction by using a third-party payment processor" if has_payments else "General data protection practices (e.g. GDPR-style principles) even at POC stage",
            ],
            "security_requirements": [
                "All passwords/credentials must be handled by the managed auth provider, never stored in application code/DB directly",
                "All API endpoints must enforce authentication except explicitly public ones",
                "Sensitive fields (payment tokens, personal identifiers) must be encrypted at rest" if has_payments else "Personal identifiers must be encrypted at rest",
            ],
            "mitigations": [
                "Delegate payment handling to a PCI-compliant processor rather than storing card data" if has_payments else "Use a managed auth provider with secure password/session handling",
                "Apply role-based access control from the start, even in the POC",
                "Log security-relevant events (login attempts, permission changes) for auditability",
            ],
        }


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.solution_architect import SolutionArchitectAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    BusinessAnalystAgent().run(ctx)
    SolutionArchitectAgent().run(ctx)
    contribution = SecurityAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

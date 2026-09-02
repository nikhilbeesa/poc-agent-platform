"""
Product Requirements Agent -> Product Requirements Document (PRD)
Answers: "What should the product do?"
Absorbs architecture + security context that affects product BEHAVIOR
(not separate documents) as dedicated sections.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class ProductRequirementsAgent(BaseAgent):
    role = AgentRole.PRODUCT_REQUIREMENTS
    max_output_tokens = 3000

    def build_prompt(self, context: ProjectContext) -> str:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        return f"""You are a product manager writing the central Product
Requirements Document (PRD) for this project. This PRD must be the
primary detailed product specification, AND it must absorb the relevant
architecture and security context that affects product behavior — do NOT
write a separate architecture or security document, just the sections
below, scoped to what actually affects product behavior/UX (not
infrastructure implementation detail a UI designer doesn't need).

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Problem: {ba_output.get('problem_statement', 'N/A')}
- Target users / personas: {ba_output.get('target_users', 'N/A')} / {ba_output.get('user_personas', [])}
- Business goals: {ba_output.get('business_goals', [])}
- Requirements: {ba_output.get('requirements', [])}
- Business rules: {ba_output.get('business_rules', [])}
- Constraints: {ba_output.get('constraints', [])}

Product manager's epics and stories: {pm_output.get('epics', [])} / {pm_output.get('stories', [])}

Rules:
- Assign each functional requirement a unique ID: FR-001, FR-002, ...
- If a technology choice is uncertain, mark it as Recommended, Alternative,
  TBD, or Open Question — never present two options as both final.
- Only include technical/security detail that actually affects product
  behavior or UX; skip infrastructure implementation minutiae.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "product_overview": "a clear paragraph describing the product",
  "product_goals": ["...", "..."],
  "target_users": "...",
  "personas": [{{"name": "...", "role": "...", "goals": "..."}}],
  "user_journeys": ["...", "..."],
  "product_capabilities": ["...", "..."],
  "functional_requirements": [{{
    "id": "FR-001", "feature": "...", "purpose": "...", "actor": "...",
    "trigger": "...", "preconditions": "...", "inputs": ["..."],
    "expected_behavior": "...", "outputs": ["..."], "user_visible_result": "...",
    "validation": "...", "error_scenarios": ["..."], "dependencies": ["..."]
  }}],
  "roles_and_permissions": [{{"role": "...", "permissions": ["..."]}}],
  "product_business_rules": ["...", "..."],
  "navigation_behavior": "...",
  "notifications_and_confirmations": ["...", "..."],
  "validation_and_error_handling": "...",
  "state_behaviors": {{"loading": "...", "empty": "...", "success": "...", "failure": "...", "processing": "..."}},
  "audit_and_versioning": "... or 'Not applicable for this POC'",
  "non_functional_requirements": ["...", "..."],
  "technical_integration_constraints": {{
    "application_type": "... (Recommended/TBD as appropriate)",
    "major_system_capabilities": ["..."],
    "external_integrations": ["... or 'None identified'"],
    "data_sources": ["..."],
    "api_dependencies": ["... or 'None identified'"],
    "real_time_requirements": "... or 'None identified'",
    "authentication_dependencies": "...",
    "platform_deployment_constraints": "..."
  }},
  "security_privacy_access_constraints": {{
    "authentication_requirements": "...",
    "mfa_requirements": "... or 'Not required for POC'",
    "roles": ["..."],
    "access_restrictions": ["..."],
    "sensitive_data_handling": "...",
    "privacy_requirements": "...",
    "audit_requirements": "... or 'Not applicable for this POC'",
    "approval_requirements": ["... or 'None identified'"],
    "ux_implications": ["... — concrete statements like 'Approve action must not be available to unauthorized roles'"]
  }},
  "success_metrics": ["...", "..."],
  "out_of_scope": ["...", "..."],
  "dependencies": ["...", "..."],
  "assumptions": ["...", "..."],
  "release_milestones": [{{"milestone": "...", "description": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        domain = (context.domain_classification or "general_business").replace("_", " ")
        epics = pm_output.get("epics", [])
        stories = pm_output.get("stories", [])
        target_users = ba_output.get("target_users", "end users")

        functional_requirements = []
        for i, story in enumerate(stories, start=1):
            fr_id = f"FR-{i:03d}"
            functional_requirements.append({
                "id": fr_id,
                "feature": story.get("feature", story.get("story", "Core feature")),
                "purpose": story.get("business_value", "Delivers core product value"),
                "actor": story.get("role", target_users),
                "trigger": story.get("trigger", "User initiates the action"),
                "preconditions": story.get("preconditions", "User is authenticated"),
                "inputs": ["User-provided data relevant to this action"],
                "expected_behavior": f"System performs: {story.get('feature', 'the core action')}",
                "outputs": ["Confirmation of the completed action"],
                "user_visible_result": "User sees a clear success confirmation",
                "validation": "Required fields must be present and valid before submission",
                "error_scenarios": ["Invalid input", "Action fails server-side"],
                "dependencies": story.get("related_br_ids", []),
            })

        has_payments = any("payment" in str(r).lower() for r in ba_output.get("requirements", []))

        return {
            "summary": f"PRD synthesizing the business case and {len(epics)} epics into {len(functional_requirements)} functional requirements for the {domain} idea.",
            "product_overview": f"{context.business_idea_raw}. This product addresses: {ba_output.get('problem_statement', 'the described problem')}",
            "product_goals": ba_output.get("business_goals", ["Deliver core value to target users"]),
            "target_users": target_users,
            "personas": ba_output.get("user_personas", [{"name": "Primary User", "role": target_users, "goals": "Complete the core workflow"}]),
            "user_journeys": [f"{target_users} discovers the platform, signs up, and completes the core workflow"],
            "product_capabilities": [e.get("name", "Core capability") for e in epics],
            "functional_requirements": functional_requirements,
            "roles_and_permissions": [
                {"role": "End User", "permissions": ["View", "Create", "Edit own records"]},
                {"role": "Admin", "permissions": ["View", "Create", "Edit", "Approve", "Reject"]},
            ],
            "product_business_rules": ba_output.get("business_rules", ["Only authenticated users may perform core actions"]),
            "navigation_behavior": "Primary navigation exposes the core workflow first; secondary items (settings, account) are accessible but not primary.",
            "notifications_and_confirmations": [
                "Success confirmation after completing the core workflow action",
                "Error message with a clear next step when an action fails",
            ],
            "validation_and_error_handling": "All forms validate required fields client-side before submission; server-side validation errors are surfaced with actionable messages.",
            "state_behaviors": {
                "loading": "Show a loading indicator while an action is processing",
                "empty": "Show a clear empty state with a call to action when no data exists yet",
                "success": "Show explicit confirmation of the completed action",
                "failure": "Show a clear error message with a retry or correction path",
                "processing": "Disable the triggering action while in progress to prevent duplicate submissions",
            },
            "audit_and_versioning": "Not applicable for this POC — TBD for a future phase if compliance requires it.",
            "non_functional_requirements": [
                "System should respond to user actions within 2 seconds under normal load",
                "System should be usable on both desktop and mobile browsers",
                "System should log key actions for auditability",
            ],
            "technical_integration_constraints": {
                "application_type": "Recommended: web application (responsive), TBD: native mobile app for a later phase",
                "major_system_capabilities": ["User account management", "Core workflow processing", "Notifications"],
                "external_integrations": ["Payment processor (TBD — specific provider not yet selected)"] if has_payments else ["None identified from discovery"],
                "data_sources": ["Primary application database (user, workflow, and transaction records)"],
                "api_dependencies": ["Payment processor API"] if has_payments else ["None identified"],
                "real_time_requirements": "None identified — standard request/response is sufficient for POC scope",
                "authentication_dependencies": "Recommended: managed authentication provider rather than custom-built auth",
                "platform_deployment_constraints": "POC scope — single environment, not yet designed for multi-region deployment",
            },
            "security_privacy_access_constraints": {
                "authentication_requirements": "All core workflow actions require an authenticated session",
                "mfa_requirements": "Not required for POC — Recommended for admin roles in a later phase",
                "roles": ["End User", "Admin"],
                "access_restrictions": ["Admin-only actions must not be visible or accessible to End User role"],
                "sensitive_data_handling": ("Payment data must never be stored directly — delegated to a PCI-compliant processor" if has_payments else "Personal identifiers should be encrypted at rest"),
                "privacy_requirements": "Standard data protection practices apply even at POC stage",
                "audit_requirements": "Not applicable for this POC",
                "approval_requirements": ["None identified from discovery"],
                "ux_implications": [
                    "Admin-only actions (e.g. approve/reject) must not be shown to End User role",
                    "Payment entry screens must clearly indicate secure handling" if has_payments else "Account settings must clearly separate sensitive fields from general profile fields",
                ],
            },
            "success_metrics": ba_output.get("success_metrics", ["User adoption within first 90 days"]),
            "out_of_scope": ba_output.get("scope_out", ["Advanced analytics/reporting (future phase)"]),
            "dependencies": ba_output.get("dependencies", []),
            "assumptions": ba_output.get("assumptions", []),
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
    ctx.discovery_questions = [DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners")]
    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    contribution = ProductRequirementsAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

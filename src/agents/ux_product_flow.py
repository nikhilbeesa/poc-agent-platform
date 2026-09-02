"""
UX / Product Flow Agent -> UX / Product Flow Specification
Answers: "How should users experience and interact with the product?"

This is THE primary document intended for the external Design AI Agent.
It translates the PRD and User Stories into structured UX requirements:
information architecture, screen inventory, user flows, screen states,
interactions, forms, navigation, notifications, roles/permissions,
responsive and accessibility considerations.

Describes WHAT each screen must contain and HOW it must behave — never
visual design, wireframes, or actual UI code. Runs after Product
Requirements (needs the FR-XXX list and roles/permissions) and after
Product Manager (needs the US-XXX stories to derive flows from).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402


class UXProductFlowAgent(BaseAgent):
    role = AgentRole.UX_PRODUCT_FLOW
    max_output_tokens = 3200

    def build_prompt(self, context: ProjectContext) -> str:
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        pm_output = pm.output if pm else {}
        prd_output = prd.output if prd else {}

        return f"""You are a UX/product flow specialist. Translate the PRD
and user stories below into a structured UX/Product Flow Specification.
This is the PRIMARY document an independent, external Design AI Agent
will use to generate UI/UX designs — it must be detailed enough that the
Design AI Agent needs nothing else. Describe WHAT each screen must
contain and HOW it must behave. Do NOT create visual designs, wireframes,
or code.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

User stories: {pm_output.get('stories', [])}
Epics: {pm_output.get('epics', [])}

PRD functional requirements: {prd_output.get('functional_requirements', [])}
Roles and permissions: {prd_output.get('roles_and_permissions', [])}
Navigation behavior: {prd_output.get('navigation_behavior', 'N/A')}
State behaviors: {prd_output.get('state_behaviors', {})}
Security/access constraints affecting UX: {prd_output.get('security_privacy_access_constraints', {}).get('ux_implications', [])}

Rules:
- Assign each screen a unique ID: SCR-001, SCR-002, ...
- Assign each user flow a unique ID: FLOW-001, FLOW-002, ...
- Reference related US-XXX / FR-XXX IDs wherever a screen or flow derives from them.
- Generate the information architecture and roles/permissions table from
  the ACTUAL product requirements — do not use generic placeholder structure.
- Do not invent requirements unsupported by the product context.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "information_architecture": ["Top-level section name", "..."],
  "screens": [{{
    "id": "SCR-001", "name": "...", "purpose": "...", "primary_role": "...",
    "entry_points": ["..."], "exit_points": ["..."],
    "related_story_ids": ["US-001"], "related_requirement_ids": ["FR-001"],
    "primary_actions": ["..."], "secondary_actions": ["..."],
    "navigation": "...", "information_displayed": ["..."], "data_required": ["..."],
    "ui_elements_required": ["..."], "permissions": "...", "business_rules": ["..."],
    "dependencies": ["..."]
  }}],
  "user_flows": [{{
    "id": "FLOW-001", "name": "...", "actor": "...", "goal": "...",
    "starting_point": "...", "preconditions": "...",
    "main_path": ["step 1 (SCR-XXX)", "step 2 (SCR-XXX)", "..."],
    "alternative_paths": ["... or 'None'"], "error_paths": ["..."],
    "decision_points": ["..."], "completion_state": "...",
    "related_screen_ids": ["SCR-001"], "related_requirement_ids": ["FR-001"], "related_story_ids": ["US-001"]
  }}],
  "screen_states": [{{"screen_id": "SCR-001", "state": "loading|empty|populated|editing|saving|processing|success|error|disabled|permission_restricted", "what_user_sees": "...", "available_actions": ["..."], "disabled_actions": ["..."], "next_step": "..."}}],
  "interactions": [{{"action": "...", "preconditions": "...", "system_behavior": "...", "user_visible_result": "...", "next_state": "...", "possible_errors": ["..."]}}],
  "forms": [{{"form_name": "...", "screen_id": "SCR-001", "fields": [{{"field": "...", "purpose": "...", "data_type": "...", "required": true, "validation": "...", "allowed_values": "... or 'N/A'", "default_value": "... or 'None'", "error_behavior": "...", "dependencies": "... or 'None'"}}]}}],
  "navigation": {{"primary_navigation": ["..."], "secondary_navigation": ["..."], "entry_paths": ["..."], "exit_paths": ["..."], "back_behavior": "...", "redirect_behavior": "..."}},
  "notifications_and_feedback": {{"success_messages": ["..."], "error_messages": ["..."], "warnings": ["..."], "confirmation_dialogs": ["..."], "informational_messages": ["..."]}},
  "roles_permissions_matrix": [{{"role": "...", "view": true, "edit": true, "approve": false, "reject": false}}],
  "responsive_requirements": {{"desktop": "...", "tablet": "...", "mobile": "..."}},
  "accessibility": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        pm_output = pm.output if pm else {}
        prd_output = prd.output if prd else {}

        stories = pm_output.get("stories", [])
        epics = pm_output.get("epics", [])
        roles = prd_output.get("roles_and_permissions", [{"role": "End User", "permissions": ["View", "Create"]}])
        role_names = [r.get("role", "End User") for r in roles]

        ia = ["Authentication", "Dashboard"] + [e.get("name", "Core") for e in epics] + ["Settings"]

        screens = [
            {"id": "SCR-001", "name": "Sign Up / Log In", "purpose": "Authenticate the user or create a new account",
             "primary_role": role_names[0] if role_names else "End User",
             "entry_points": ["First visit", "Logged-out state"], "exit_points": ["Dashboard"],
             "related_story_ids": [s["id"] for s in stories if "sign up" in s.get("story", "").lower()] or ["US-002"],
             "related_requirement_ids": ["FR-001"],
             "primary_actions": ["Sign up", "Log in"], "secondary_actions": ["Forgot password"],
             "navigation": "Entry point before any authenticated screen", "information_displayed": ["Sign-up/login form"],
             "data_required": ["Email/identifier", "Password"], "ui_elements_required": ["Text input", "Password input", "Submit button"],
             "permissions": "Public — no authentication required", "business_rules": ["Requires a valid, unique identifier"],
             "dependencies": []},
            {"id": "SCR-002", "name": "Dashboard", "purpose": "Primary landing screen after authentication",
             "primary_role": role_names[0] if role_names else "End User",
             "entry_points": ["Post sign-up/login"], "exit_points": [f"SCR-00{i+3}" for i in range(min(len(epics), 2))],
             "related_story_ids": [s["id"] for s in stories], "related_requirement_ids": [f"FR-{i+1:03d}" for i in range(len(stories))],
             "primary_actions": ["Navigate to core workflow"], "secondary_actions": ["Access settings"],
             "navigation": "Central hub linking to all primary epics", "information_displayed": ["Summary of user's current state/activity"],
             "data_required": ["User's existing records, if any"], "ui_elements_required": ["Navigation menu", "Summary cards"],
             "permissions": f"Authenticated {role_names[0] if role_names else 'End User'}", "business_rules": [], "dependencies": ["SCR-001"]},
        ]
        for i, epic in enumerate(epics, start=3):
            related = [s["id"] for s in stories if s.get("epic_id") == epic.get("id")]
            screens.append({
                "id": f"SCR-{i:03d}", "name": epic.get("name", "Core Screen"), "purpose": epic.get("description", "Supports a core epic"),
                "primary_role": role_names[0] if role_names else "End User",
                "entry_points": ["SCR-002"], "exit_points": ["SCR-002"],
                "related_story_ids": related, "related_requirement_ids": [f"FR-{j+1:03d}" for j, s in enumerate(stories) if s.get("epic_id") == epic.get("id")],
                "primary_actions": ["Perform the core action for this epic"], "secondary_actions": ["Cancel", "Go back"],
                "navigation": "Reached from the Dashboard", "information_displayed": ["Relevant data for this epic"],
                "data_required": ["User input specific to this workflow"], "ui_elements_required": ["Form or list view", "Action buttons"],
                "permissions": f"Authenticated {role_names[0] if role_names else 'End User'}", "business_rules": [], "dependencies": ["SCR-002"],
            })

        flows = []
        for i, story in enumerate(stories, start=1):
            related_screens = ["SCR-002"] + [s["id"] for s in screens if story.get("id") in s.get("related_story_ids", [])]
            flows.append({
                "id": f"FLOW-{i:03d}", "name": f"Flow: {story.get('feature', story.get('story', 'Core action'))}",
                "actor": story.get("role", "End User"), "goal": story.get("business_value", "Complete the core action"),
                "starting_point": "Dashboard", "preconditions": story.get("preconditions", "User is authenticated"),
                "main_path": story.get("main_flow", ["Navigate to screen", "Perform action", "See confirmation"]),
                "alternative_paths": [story.get("alternative_flow", "None")],
                "error_paths": [story.get("exception_flow", "System shows a clear error")],
                "decision_points": [], "completion_state": "Action completed and confirmed to the user",
                "related_screen_ids": list(dict.fromkeys(related_screens)),
                "related_requirement_ids": [f"FR-{i:03d}"], "related_story_ids": [story.get("id", f"US-{i:03d}")],
            })

        screen_states = []
        for s in screens[1:]:
            screen_states.append({"screen_id": s["id"], "state": "loading", "what_user_sees": "A loading indicator while data/actions are processed",
                                   "available_actions": [], "disabled_actions": s.get("primary_actions", []), "next_step": "Transitions to populated or error state"})
            screen_states.append({"screen_id": s["id"], "state": "empty", "what_user_sees": "A clear empty state with guidance on what to do next",
                                   "available_actions": s.get("primary_actions", []), "disabled_actions": [], "next_step": "User creates the first record"})
            screen_states.append({"screen_id": s["id"], "state": "error", "what_user_sees": "A clear error message explaining what went wrong",
                                   "available_actions": ["Retry"], "disabled_actions": s.get("primary_actions", []), "next_step": "User retries or navigates away"})

        interactions = [{
            "action": s.get("primary_actions", ["Submit"])[0] if s.get("primary_actions") else "Submit",
            "preconditions": s.get("permissions", "User is authenticated"),
            "system_behavior": "System validates input and processes the request",
            "user_visible_result": "User sees a success confirmation",
            "next_state": "success", "possible_errors": ["Validation failure", "Server error"],
        } for s in screens[2:]] or [{"action": "Submit", "preconditions": "User is authenticated", "system_behavior": "System processes the request",
                                      "user_visible_result": "Success confirmation shown", "next_state": "success", "possible_errors": ["Validation failure"]}]

        forms = [{
            "form_name": f"{s['name']} form", "screen_id": s["id"],
            "fields": [
                {"field": "Primary input", "purpose": "Captures the core data for this action", "data_type": "text",
                 "required": True, "validation": "Must not be empty", "allowed_values": "N/A", "default_value": "None",
                 "error_behavior": "Inline error message under the field", "dependencies": "None"},
            ],
        } for s in screens if s["id"] not in ("SCR-001", "SCR-002")] or [{
            "form_name": "Sign up form", "screen_id": "SCR-001",
            "fields": [
                {"field": "Email", "purpose": "Unique identifier for the account", "data_type": "email", "required": True,
                 "validation": "Must be a valid email format", "allowed_values": "N/A", "default_value": "None",
                 "error_behavior": "Inline error if invalid or already in use", "dependencies": "None"},
                {"field": "Password", "purpose": "Account credential", "data_type": "password", "required": True,
                 "validation": "Minimum length requirement", "allowed_values": "N/A", "default_value": "None",
                 "error_behavior": "Inline error if too short", "dependencies": "None"},
            ],
        }]

        return {
            "summary": f"UX specification covering {len(screens)} screens and {len(flows)} user flows derived from {len(stories)} user stories.",
            "information_architecture": list(dict.fromkeys(ia)),
            "screens": screens,
            "user_flows": flows,
            "screen_states": screen_states,
            "interactions": interactions,
            "forms": forms,
            "navigation": {
                "primary_navigation": [e.get("name", "Core") for e in epics],
                "secondary_navigation": ["Settings", "Account"],
                "entry_paths": ["Sign up", "Log in"],
                "exit_paths": ["Log out"],
                "back_behavior": "Returns to the previous screen in the navigation stack",
                "redirect_behavior": "Unauthenticated users attempting a protected screen are redirected to Sign Up / Log In",
            },
            "notifications_and_feedback": {
                "success_messages": ["Action completed successfully"],
                "error_messages": ["Something went wrong. Please try again."],
                "warnings": ["Unsaved changes will be lost if you leave this screen"],
                "confirmation_dialogs": ["Are you sure you want to proceed?"],
                "informational_messages": ["No data yet — get started by creating your first record"],
            },
            "roles_permissions_matrix": [
                {"role": r.get("role", "End User"), "view": True, "edit": "Edit" in r.get("permissions", []),
                 "approve": "Approve" in r.get("permissions", []), "reject": "Reject" in r.get("permissions", [])}
                for r in roles
            ],
            "responsive_requirements": {
                "desktop": "Full navigation and multi-column layouts supported",
                "tablet": "Condensed navigation, single or two-column layouts",
                "mobile": "Primary actions accessible within one thumb-reach; navigation collapses to a menu",
            },
            "accessibility": [
                "All primary actions must be reachable via keyboard navigation",
                "All form fields must have accessible labels",
                "Status indicators (success/error) must not rely on color alone",
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
    ctx.discovery_questions = [DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners")]
    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    ProductRequirementsAgent().run(ctx)
    contribution = UXProductFlowAgent().run(ctx)
    print(json.dumps(contribution.model_dump(), indent=2, default=str))

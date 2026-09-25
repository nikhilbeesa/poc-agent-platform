"""
UX / Product Flow Agent -> UX Product Flow Specification
Answers: "How does this actually work on screen, click by click?"
Primary handoff document to the Design AI Agent.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402
import content_kit as ck  # noqa: E402


class UXProductFlowAgent(BaseAgent):
    role = AgentRole.UX_PRODUCT_FLOW
    max_output_tokens = 12000

    def build_prompt(self, context: ProjectContext) -> str:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}
        prd_output = prd.output if prd else {}

        return f"""{self.resolution_notes_block(context)}You are a senior UX designer producing the UX / Product
Flow Specification — the primary handoff document to the Design AI
Agent. It must be comprehensive: a dedicated screen for every module,
a dedicated flow for every user story, explicit states, forms, and
interactions — not a handful of samples. This is typically a 40+ page
document.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Modules: {ba_output.get('modules', [])}
Roles: {ba_output.get('roles', [])}
Functional requirements: {prd_output.get('functional_requirements', [])}
User stories: {pm_output.get('stories', [])}
Data entities: {ba_output.get('data_entities', [])}

For every module, break it into as many distinct screens as its actual
requirements justify — a module that bundles browsing, creating/editing,
viewing detail, admin moderation, and settings-type requirements needs a
separate screen for each of those (e.g. "Listings — Browse & Search",
"Listings — Create / Edit", "Listings — Admin / Moderation"), not one
generic screen covering all of them. Only keep a single screen for a
module whose requirements are genuinely all the same kind of action.
Every screen (id, name, purpose, primary role, entry/exit points, related
story/requirement IDs, primary/secondary actions, navigation, information
displayed, data required, UI elements required, permissions, business
rules, dependencies) must describe what that specific screen contains and
what the user can do there — never a generic placeholder like "data
relevant to this module". For every user story, define a corresponding
user flow (id, name, actor, goal, starting point, preconditions, numbered
main path, alternative paths, error paths, decision points, completion
state, related screens/requirements/stories). Also define: information architecture; screen states (loading/
empty/success/failure) for the key screens; key interactions; forms with
full field-level detail (purpose, type, required, validation, default)
for every data-entry screen; navigation structure; notifications &
feedback patterns; a role/permission matrix (view/edit/approve/reject);
responsive requirements; and accessibility requirements.

CRITICAL TRACEABILITY RULE: every single functional requirement id listed
above must appear in related_requirement_ids of at least one screen OR at
least one user flow — there must be no functional requirement left with
no screen and no flow. Before finalizing, check every FR id off this
list; if one has no home, add the screen/flow it needs rather than
leaving it out.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "information_architecture": ["...", "..."],
  "screens": [{{
    "id": "SCR-001", "name": "...", "purpose": "...", "primary_role": "...",
    "entry_points": ["..."], "exit_points": ["..."],
    "related_story_ids": ["..."], "related_requirement_ids": ["..."],
    "primary_actions": ["..."], "secondary_actions": ["..."], "navigation": "...",
    "information_displayed": ["..."], "data_required": ["..."], "ui_elements_required": ["..."],
    "permissions": "...", "business_rules": ["..."], "dependencies": ["..."]
  }}],
  "user_flows": [{{
    "id": "FLOW-001", "name": "...", "actor": "...", "goal": "...",
    "starting_point": "...", "preconditions": "...", "main_path": ["...", "..."],
    "alternative_paths": ["..."], "error_paths": ["..."], "decision_points": ["..."],
    "completion_state": "...", "related_screen_ids": ["..."], "related_requirement_ids": ["..."], "related_story_ids": ["..."]
  }}],
  "screen_states": [{{"screen_id": "...", "state": "loading|empty|success|failure", "what_user_sees": "...", "available_actions": ["..."], "disabled_actions": ["..."], "next_step": "..."}}],
  "interactions": [{{"action": "...", "preconditions": "...", "system_behavior": "...", "user_visible_result": "...", "next_state": "...", "possible_errors": ["..."]}}],
  "forms": [{{"form_name": "...", "screen_id": "...", "fields": [{{"field": "...", "purpose": "...", "data_type": "...", "required": true, "validation": "...", "default_value": "..."}}]}}],
  "navigation": {{"primary": "...", "secondary": "...", "mobile": "..."}},
  "notifications_and_feedback": {{"success": "...", "error": "...", "loading": "...", "empty": "..."}},
  "roles_permissions_matrix": [{{"role": "...", "view": true, "edit": true, "approve": false, "reject": false}}],
  "responsive_requirements": {{"desktop": "...", "tablet": "...", "mobile": "..."}},
  "accessibility": ["...", "..."]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        modules = ck.select_modules(context)
        roles = ck.build_roles(modules, context)
        requirements = ck.build_functional_requirements(modules)
        stories = pm_output.get("stories") or ck.build_stories(requirements, modules, context)
        screens = ck.build_screens(modules, stories, roles, context)
        flows = ck.build_flows(stories, screens, context)

        information_architecture = ["Sign Up / Log In", "Dashboard / Home"] + [m["name"] for m in modules if m["key"] not in ("authentication", "security", "notifications_module")] + ["Account Settings"]

        screen_states = []
        for s in screens[:10]:
            screen_states.append({"screen_id": s["id"], "state": "loading", "what_user_sees": "A loading indicator in place of the content area", "available_actions": [], "disabled_actions": s.get("primary_actions", []), "next_step": "Content renders once data loads"})
            screen_states.append({"screen_id": s["id"], "state": "empty", "what_user_sees": "A clear empty state with guidance and a primary call to action", "available_actions": s.get("primary_actions", [])[:1], "disabled_actions": [], "next_step": "User takes the primary action to populate the screen"})
            screen_states.append({"screen_id": s["id"], "state": "success", "what_user_sees": "Populated content reflecting the current data", "available_actions": s.get("primary_actions", []), "disabled_actions": [], "next_step": "User continues to the next relevant screen"})
            screen_states.append({"screen_id": s["id"], "state": "failure", "what_user_sees": "A clear error message explaining what went wrong and how to proceed", "available_actions": ["Retry"], "disabled_actions": s.get("primary_actions", []), "next_step": "User retries or contacts support"})

        interactions = []
        for m in modules:
            for f in m["fr"][:2]:
                interactions.append({
                    "action": f["name"], "preconditions": f"Acting user has the permissions required for {f['name']}",
                    "system_behavior": f["description"], "user_visible_result": "Clear confirmation of the completed action",
                    "next_state": "Success state, or the next step in the related flow", "possible_errors": ["Validation error", "Permission denied", "Server error"],
                })

        forms = []
        for m in modules:
            entity_items = list(m["entities"].items())
            if not entity_items:
                continue
            entity_name, fields = entity_items[0]
            create_fr = next((f for f in m["fr"] if any(k in f["name"].lower() for k in ("create", "registration", "edit", "onboarding", "submit"))), None)
            if not create_fr:
                continue
            screen = next((s for s in screens if s["name"] == m["name"]), None)
            forms.append({
                "form_name": f"{create_fr['name']} Form", "screen_id": screen["id"] if screen else "N/A",
                "fields": [{
                    "field": field, "purpose": f"Captures the {field.lower()} for this {entity_name}",
                    "data_type": "Text" if not any(k in field.lower() for k in ("date", "amount", "price", "id", "status")) else ("Date" if "date" in field.lower() else ("Number" if any(k in field.lower() for k in ("amount", "price")) else "Text")),
                    "required": field.lower() not in ("photo url", "media urls", "preferences"),
                    "validation": "Required, format-validated" if field.lower() not in ("photo url", "media urls", "preferences") else "Optional",
                    "default_value": "None",
                } for field in fields],
            })

        roles_permissions_matrix = []
        for r in roles:
            is_admin = r["role"] == "Admin"
            is_support = r["role"] == "Support Agent"
            roles_permissions_matrix.append({"role": r["role"], "view": True, "edit": not is_support, "approve": is_admin, "reject": is_admin})

        return {
            "summary": f"UX specification covering {len(screens)} screens and {len(flows)} user flows derived from {len(stories)} user stories across {len(modules)} modules.",
            "information_architecture": information_architecture,
            "screens": screens,
            "user_flows": flows,
            "screen_states": screen_states,
            "interactions": interactions,
            "forms": forms,
            "navigation": {
                "primary": "Left sidebar (desktop) / bottom tab bar (mobile) exposing Dashboard plus one entry per core module",
                "secondary": "Account settings and support accessible from a persistent header menu",
                "mobile": "Bottom tab bar collapses secondary items into a 'More' menu",
            },
            "notifications_and_feedback": {
                "success": "Toast/banner confirming the action, auto-dismissing after a few seconds",
                "error": "Inline field-level errors plus a summary banner for form-level failures",
                "loading": "Skeleton or spinner in place of content; primary actions disabled while in flight",
                "empty": "Illustration or message plus a clear primary call to action",
            },
            "roles_permissions_matrix": roles_permissions_matrix,
            "responsive_requirements": {
                "desktop": "Full multi-column layouts; primary navigation always visible",
                "tablet": "Collapsible navigation; core flows remain single-column where content is form-heavy",
                "mobile": "Single-column layouts; bottom tab navigation; touch targets at least 44x44px",
            },
            "accessibility": ba_output.get("accessibility") or [
                "Target WCAG 2.2 AA across primary flows",
                "All interactive elements reachable and operable via keyboard",
                "Form fields have accessible labels and non-color-only error indication",
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

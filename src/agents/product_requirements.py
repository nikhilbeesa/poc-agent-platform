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
import content_kit as ck  # noqa: E402


def _split_capabilities(text: str) -> list:
    """Split a comma-separated capabilities string into clean list items."""
    if not text:
        return ["View", "Create", "Edit own records"]
    return [p.strip() for p in text.split(",") if p.strip()]


# Per-capability technical/security notes for every module that inherently
# needs one beyond the PRD's generic platform-wide sections (kept in sync
# with coverage.py's _REQUIRES_DISTINCT_TECHNICAL_HINTS /
# _REQUIRES_DISTINCT_SECURITY_HINTS, which look for the module's own name
# in this text — so every one of these notes must actually name the
# capability it's about).
_TECHNICAL_NOTE_BY_MODULE_KEY = {
    "payments": "Payments & Billing: payment capture/refunds are delegated to a tokenizing, PCI-compliant processor; the platform never stores raw card data and only holds a processor-issued reference.",
    "scheduling": "Scheduling & Availability: slot computation and a short-lived hold during checkout must be handled with a concurrency-safe check to prevent two confirmations of the same slot.",
    "trust_safety": "Trust & Safety: identity verification and escrow/dispute handling depend on a verification provider and a payment provider that supports held/released funds.",
    "fulfilment": "Fulfilment & Delivery: shipment status depends on a carrier integration (webhook or polling) in addition to seller-entered manual updates.",
    "ai_features": "AI-Powered Features: requires an AI/ML component with a bounded-latency call, a confidence score in its response, and a defined timeout/fallback path — see the AI Feature Specifications below.",
    "data_export_import": "Data Export & Import: bulk import needs row-level validation before commit; export must run within the requesting user's access scope and reasonable size/rate limits.",
    "integrations_module": "Third-Party Integrations: each connection needs OAuth-based (or provider-appropriate) authorization, a revoke path, and failure/backoff handling for sync jobs.",
    "offline_sync": "Offline Access & Synchronization: requires a local data cache, a queued-action store, and a conflict-detection strategy (e.g. last-write-wins with surfaced conflicts) on reconnect.",
    "subscription_billing": "Subscription & Plan Management: recurring billing depends on a billing provider with webhook support for payment success/failure and entitlement state kept in sync with billing status.",
}

_SECURITY_NOTE_BY_MODULE_KEY = {
    "authentication": "Authentication & Account Management: passwords/OTPs are hashed/never logged in plaintext; sessions expire on idle timeout and are invalidated on password change.",
    "user_profile": "User Profile Management: a user may only view/edit their own profile; changing the primary contact identifier requires re-verification.",
    "payments": "Payments & Billing: raw payment credentials are never stored by the platform; only a processor token/reference is retained, and refunds cannot exceed the original captured amount.",
    "trust_safety": "Trust & Safety: identity documents are treated as restricted data — access-logged, never exposed even to Admin without an explicit, logged justification.",
    "admin_ops": "Admin & Operations Console: every manual override is recorded with actor, timestamp, and reason in an append-only audit log; destructive actions require explicit confirmation.",
    "ai_features": "AI-Powered Features: AI input/output logs must not retain more personal data than needed for quality review and must be access-restricted like other user data.",
    "privacy_consent": "Privacy, Consent & Data Retention: account deletion and data-export requests are authenticated before acting on them; deleted data is removed or irreversibly anonymized within the published retention window.",
    "subscription_billing": "Subscription & Plan Management: entitlement is re-evaluated server-side on each relevant action, never trusted from client state alone.",
    "integrations_module": "Third-Party Integrations: connections are revocable at any time, and only the minimum OAuth scopes the integration actually needs are requested.",
}


class ProductRequirementsAgent(BaseAgent):
    role = AgentRole.PRODUCT_REQUIREMENTS
    max_output_tokens = 12000

    def build_prompt(self, context: ProjectContext) -> str:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        ba_output = ba.output if ba else {}
        pm_output = pm.output if pm else {}

        return f"""{self.resolution_notes_block(context)}You are a product manager writing the central Product
Requirements Document (PRD) for this project — the primary detailed
product specification, long and thorough (dozens of pages), not a short
summary. It must absorb the relevant architecture and security context
that affects product behavior — do NOT write a separate architecture or
security document, just the sections below, scoped to what actually
affects product behavior/UX (not infrastructure implementation detail a
UI designer doesn't need). Every functional requirement from the
business analyst's list must get its own detailed PRD-level breakdown —
do not sample or cap the list.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Business analyst's findings:
- Problem statement: {ba_output.get('problem_statement', 'N/A')}
- Target users / personas: {ba_output.get('target_users', 'N/A')} / {ba_output.get('user_personas', [])}
- Business objectives: {ba_output.get('business_objectives', [])}
- Functional requirements: {ba_output.get('requirements', [])}
- Business rules: {ba_output.get('business_rules', [])}
- NFRs: {ba_output.get('nfrs', [])}
- Roles: {ba_output.get('roles', [])}
- Integrations: {ba_output.get('integrations', [])}
- Constraints: {ba_output.get('constraints', [])}

Product manager's epics and stories: {pm_output.get('epics', [])} / {pm_output.get('stories', [])}

Rules:
- Reuse the same FR IDs the business analyst assigned (FR-001, FR-002, ...) — do not renumber.
- If a technology choice is uncertain, mark it as Recommended, Alternative,
  TBD, or Open Question — never present two options as both final.
- Only include technical/security detail that actually affects product
  behavior or UX; skip infrastructure implementation minutiae.
- Do NOT claim GDPR, CCPA, SOC 2, PCI DSS, HIPAA, or any other specific
  compliance regime unless the business idea or discovery answers actually
  support it — otherwise say the applicable regulation must be confirmed.
- For every module/capability that carries technology-specific risk
  (payments, AI/ML, third-party integrations, offline/sync, scheduling,
  trust & safety, fulfilment, data export/import, subscriptions) write a
  capability_technical_notes entry that names that exact capability —
  never leave a technical capability covered only by generic platform-wide
  text. Do the same for security-sensitive capabilities (authentication,
  payments, profile, trust & safety, admin, AI/ML, privacy/consent,
  subscriptions, integrations) in capability_security_notes.
- If the business idea or discovery answers describe ANY AI/ML-powered
  behavior (recommendations, generated content, predictions, matching,
  a chatbot/assistant, personalization, etc.), you MUST populate
  ai_feature_specifications with one full entry per such AI capability —
  never describe an AI feature only in passing prose elsewhere. If there
  is no AI-powered behavior in this product, return an empty list.
- mvp_scope, phase_2_scope, and future_scope must be mutually exclusive
  and together account for every functional requirement — never leave a
  requirement unassigned to any of the three, and never contradict the
  business analyst's own P0-P3 prioritization or the discovery answers'
  stated scope decisions.
- navigation_pattern is the single source of truth for navigation: pick
  ONE pattern and state it as a short, exact label. Every other document
  in this package (most importantly the UX/Product Flow Specification)
  will be told to reuse that exact label verbatim rather than choosing
  its own — so do not hedge with "or" between two different structures,
  and do not describe a hybrid unless it is genuinely one coherent,
  named pattern (e.g. "Sidebar (desktop) + hamburger drawer (mobile)" is
  fine as ONE pattern; "Top nav bar, OR a sidebar, OR a hamburger menu"
  is not).
- roles_and_permissions (and security_privacy_access_constraints.roles)
  is the single source of truth for who can do what. Do not grant an
  action to a role here that the functional requirements don't actually
  support, and do not leave an action mentioned elsewhere in the PRD
  ungoverned by a role here — the UX spec will build its permission
  matrix strictly from this list and cannot invent additional
  capabilities for any role.

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
  "navigation_pattern": "EXACTLY ONE short label naming the single navigation pattern for the whole product, e.g. 'Top navigation bar (desktop and mobile)' or 'Left sidebar (desktop) + bottom tab bar (mobile)' — never describe two different structures as both in use",
  "navigation_behavior": "1-3 sentences elaborating on navigation_pattern (what's in it, ordering, what's primary vs secondary) — must be a direct elaboration of navigation_pattern, never a different or additional pattern",
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
    "platform_deployment_constraints": "...",
    "capability_technical_notes": [{{"capability": "the exact module/capability name used in the BRD", "note": "the specific technical consideration for THIS capability — do not write a note that could apply to any capability interchangeably"}}]
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
    "ux_implications": ["... — concrete statements like 'Approve action must not be available to unauthorized roles'"],
    "capability_security_notes": [{{"capability": "the exact module/capability name used in the BRD", "note": "the specific security/privacy consideration for THIS capability"}}]
  }},
  "ai_feature_specifications": [{{
    "feature": "...", "purpose": "...", "input_data": "...", "trigger": "...", "processing_behavior": "...",
    "output": "...", "confidence_handling": "...", "explainability": "...", "user_control": "...",
    "edit_override_behavior": "...", "failure_behavior": "...", "fallback_behavior": "...",
    "privacy_considerations": "...", "data_usage": "...", "security_considerations": "...",
    "performance_expectations": "...", "related_fr": "FR-0XX"
  }}],
  "mvp_scope": ["FR-001 — ...", "..."],
  "phase_2_scope": ["...", "..."],
  "future_scope": ["...", "..."],
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
        target_users = ba_output.get("target_users") or ck.target_users_phrase(context)
        has_payments = ba_output.get("payment_requirements") is not None

        selected_modules = ck.select_modules(context)
        modules_by_key = {m["key"]: m for m in selected_modules}
        capability_technical_notes = [
            {"capability": modules_by_key[key]["name"], "note": note}
            for key, note in _TECHNICAL_NOTE_BY_MODULE_KEY.items() if key in modules_by_key
        ]
        capability_security_notes = [
            {"capability": modules_by_key[key]["name"], "note": note}
            for key, note in _SECURITY_NOTE_BY_MODULE_KEY.items() if key in modules_by_key
        ]

        ai_module = modules_by_key.get("ai_features")
        ai_feature_specifications = [
            {
                "feature": fr["name"],
                "purpose": fr["description"],
                "input_data": "User/behavioral data the user has consented to use, the specific triggering event, and relevant catalog data (see the AI-Powered Features module in the BRD).",
                "trigger": "The defined user action or system event that requests this AI output (e.g. viewing a list, completing a transaction).",
                "processing_behavior": "Runs the AI/ML component against the input data and attaches a confidence signal to the result.",
                "output": "A recommendation, generated content item, or prediction, clearly labeled as AI-generated.",
                "confidence_handling": "Results below the configured confidence threshold are not shown as authoritative; they route to the fallback below.",
                "explainability": "A short, human-readable reason is shown alongside any AI output that affects a user decision (see 'Explain AI Result').",
                "user_control": "The user may accept, edit, or dismiss the AI output; it never takes a binding action automatically.",
                "edit_override_behavior": "Editing or overriding the AI output is always available before it is saved, published, or acted upon (see 'Override / Edit AI Output').",
                "failure_behavior": "On component failure or timeout, the system falls back to the defined non-AI default rather than blocking the user.",
                "fallback_behavior": "The non-AI default is the equivalent manual flow (e.g. standard search/browse) with a clear, non-alarming explanation that the AI suggestion is unavailable.",
                "privacy_considerations": "Only data the user has consented to use as AI input is used; the user may opt out and fall back to the non-personalized experience.",
                "data_usage": "Input data usage is disclosed to the user in-product (see 'AI Data Usage & Opt-Out Controls'); no undisclosed secondary use.",
                "security_considerations": "AI input/output logs must not retain more personal data than needed for quality review, and must be access-restricted like other user data.",
                "performance_expectations": "Bounded latency with a timeout that triggers the fallback rather than an indefinite wait.",
                "related_fr": None,
            }
            for fr in (ai_module["fr"] if ai_module else [])
        ] if ai_module else []
        # Attach the real FR ids assigned in the BRD, matching on feature name.
        if ai_feature_specifications:
            fr_id_by_name = {r.get("name"): r.get("id") for r in ba_output.get("requirements", [])}
            for spec in ai_feature_specifications:
                spec["related_fr"] = fr_id_by_name.get(spec["feature"], spec["related_fr"])

        # mvp_prioritization's P0/P1/P2/P3 lists already carry "FR-xxx — Name"
        # strings from the BRD (see BusinessAnalystAgent.mock_response), so the
        # PRD's MVP/Phase-2/Future split stays consistent with the BRD's own
        # priority calls rather than re-deciding scope independently.
        mvp_prioritization = ba_output.get("mvp_prioritization", {})
        mvp_scope = list(mvp_prioritization.get("P0", [])) + list(mvp_prioritization.get("P1", []))
        phase_2_scope = list(mvp_prioritization.get("P2", []))
        future_scope = list(mvp_prioritization.get("P3", [])) + list(ba_output.get("future_enhancements", []))

        story_dep_to_fr = {s["id"]: (s.get("related_fr_ids") or [None])[0] for s in stories}

        functional_requirements = []
        for story in stories:
            fr_id = story.get("related_fr_ids", [None])[0] or story["id"].replace("US-", "FR-")
            bucket = ck._classify_fr(story.get("feature", ""), story.get("business_value", ""))
            dep_fr_ids = [d for d in (story_dep_to_fr.get(dep, dep) for dep in story.get("dependencies", [])) if d]
            main_flow = story.get("main_flow", [])
            inputs_desc = main_flow[1] if len(main_flow) > 1 else "Data captured in the corresponding user story's main flow"
            business_rules_here = story.get("business_rules", [])
            validation = ("Enforces: " + "; ".join(business_rules_here[:2])) if business_rules_here else "Required fields must be present and valid before submission"
            error_scenarios = [
                story.get("exception_flow", "System displays a clear, specific error message and preserves the user's input"),
                "Query returns no results or the data source is temporarily unavailable" if bucket == "browse" else "Permission denied for the acting role",
                "Required field missing or fails format validation",
            ]
            functional_requirements.append({
                "id": fr_id,
                "feature": story.get("feature", story.get("story", "Core feature")),
                "purpose": story.get("business_value", "Delivers core product value"),
                "actor": story.get("role", target_users),
                "trigger": story.get("trigger", "User initiates the action"),
                "preconditions": story.get("preconditions", "User is authenticated"),
                "inputs": [inputs_desc],
                "expected_behavior": f"System performs: {story.get('feature', 'the core action')}. {story.get('business_value', '')}",
                "outputs": ["Confirmation of the completed action", "Updated record state"],
                "user_visible_result": "User sees a clear success confirmation and, where applicable, the updated record",
                "validation": validation,
                "error_scenarios": error_scenarios,
                "dependencies": dep_fr_ids,
            })

        roles_and_permissions = [
            {"role": r["role"], "permissions": _split_capabilities(r.get("capabilities", ""))}
            for r in ba_output.get("roles", [])
        ] or [
            {"role": "End User", "permissions": ["View", "Create", "Edit own records"]},
            {"role": "Admin", "permissions": ["View", "Create", "Edit", "Approve", "Reject"]},
        ]

        nfrs = ba_output.get("nfrs", [])
        non_functional_requirements = [f"{n['id']} [{n['category']}] {n['requirement']}" for n in nfrs] or [
            "System should respond to user actions within 2 seconds under normal load",
            "System should be usable on both desktop and mobile browsers",
        ]

        integrations = ba_output.get("integrations", [])

        return {
            "summary": f"PRD synthesizing the business case and {len(epics)} epics into {len(functional_requirements)} fully detailed functional requirements for the {domain} product.",
            "product_overview": f"{context.business_idea_raw}. This product addresses the problems identified in the Business Requirements Document by giving {target_users} a structured, end-to-end digital workflow in place of manual coordination.",
            "product_goals": ba_output.get("business_objectives", ["Deliver core value to target users"]),
            "target_users": target_users,
            "personas": ba_output.get("user_personas") or [{"name": "Primary User", "role": target_users, "goals": "Complete the core workflow"}],
            "user_journeys": [f"{name}: {desc}" for name, desc in ba_output.get("user_journeys", {}).items()] or [f"{target_users} discovers the platform, signs up, and completes the core workflow"],
            "product_capabilities": [e.get("name", "Core capability") for e in epics],
            "functional_requirements": functional_requirements,
            "roles_and_permissions": roles_and_permissions,
            "product_business_rules": [f"{b['id']}: {b['rule']}" for b in ba_output.get("business_rules", [])] or ["Only authenticated users may perform core actions"],
            "navigation_pattern": "Top navigation bar (desktop and mobile)",
            "navigation_behavior": f"A single top navigation bar surfaces the core {domain} workflow first ({', '.join(e['name'] for e in epics[:4])}); secondary items (settings, account, support) are accessible from it but not primary.",
            "notifications_and_confirmations": [f"{n['event']} — delivered via {n['channel']}" for n in ba_output.get("notifications_matrix", [])[:12]] or [
                "Success confirmation after completing the core workflow action",
                "Error message with a clear next step when an action fails",
            ],
            "validation_and_error_handling": "All forms validate required fields client-side before submission; server-side validation errors are surfaced with actionable, field-specific messages. Every functional requirement above defines its own error scenarios explicitly rather than relying on a single generic error state.",
            "state_behaviors": {
                "loading": "Show a loading indicator while an action is processing",
                "empty": "Show a clear empty state with a call to action when no data exists yet",
                "success": "Show explicit confirmation of the completed action",
                "failure": "Show a clear error message with a retry or correction path",
                "processing": "Disable the triggering action while in progress to prevent duplicate submissions",
            },
            "audit_and_versioning": "Admin/Operations actions are recorded in an append-only audit log (see BRD Section 24). Full version history of records is not required for the MVP scope.",
            "non_functional_requirements": non_functional_requirements,
            "technical_integration_constraints": {
                "application_type": "Recommended: responsive web application; TBD: native mobile app for a later phase",
                "major_system_capabilities": [e.get("name", "") for e in epics],
                "external_integrations": [i["integration"] for i in integrations] or ["None identified from discovery"],
                "data_sources": [f"{e['entity']} records" for e in ba_output.get("data_entities", [])[:6]] or ["Primary application database"],
                "api_dependencies": [i["integration"] + " API" for i in integrations if i["integration"] != "Analytics"] or ["None identified"],
                "real_time_requirements": ("Slot-holding during checkout requires near-real-time availability checks; otherwise standard request/response is sufficient."
                                            if any(m.get("key") == "scheduling" for m in ck.select_modules(context))
                                            else "None identified — standard request/response is sufficient for MVP scope"),
                "authentication_dependencies": "Recommended: managed authentication provider rather than custom-built auth",
                "platform_deployment_constraints": "POC/MVP scope — single environment and region initially, not yet designed for multi-region deployment",
                "capability_technical_notes": capability_technical_notes,
            },
            "security_privacy_access_constraints": {
                "authentication_requirements": "All core workflow actions require an authenticated session (see FR-001/FR-002 in the Functional Requirements above)",
                "mfa_requirements": "Not required for MVP — Recommended for Admin roles in a later phase",
                "roles": [r["role"] for r in ba_output.get("roles", [])] or ["End User", "Admin"],
                "access_restrictions": [f"{r['role']}: {r.get('restricted', 'N/A')}" for r in ba_output.get("roles", [])],
                "sensitive_data_handling": ("Payment data must never be stored directly — delegated to a PCI-compliant processor (see BRD Section 23)" if has_payments else "Personal identifiers should be encrypted at rest"),
                "privacy_requirements": ba_output.get("privacy_compliance", "Standard data protection practices apply even at MVP stage"),
                "audit_requirements": "Admin/Operations actions are logged; see BRD Section 24",
                "approval_requirements": ["None identified from discovery"],
                "ux_implications": [
                    "Admin-only actions (e.g. approve/reject, moderation, overrides) must not be shown to non-Admin roles",
                    ("Payment entry screens must clearly indicate secure handling" if has_payments else "Account settings must clearly separate sensitive fields from general profile fields"),
                ],
                "capability_security_notes": capability_security_notes,
            },
            "ai_feature_specifications": ai_feature_specifications,
            "mvp_scope": mvp_scope or [f"Core {domain} workflow"],
            "phase_2_scope": phase_2_scope,
            "future_scope": future_scope,
            "success_metrics": [k["kpi"] for k in ba_output.get("kpis", [])] or ["User adoption within first 90 days"],
            "out_of_scope": ba_output.get("scope_out", ["Advanced analytics/reporting (future phase)"]),
            "dependencies": ba_output.get("dependencies", []),
            "assumptions": ba_output.get("assumptions", []),
            "release_milestones": [
                {"milestone": r["phase"], "description": r["description"]} for r in ba_output.get("release_strategy", [])
            ] or [
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

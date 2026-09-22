"""
Business Analyst Agent -> Business Requirements Document (BRD)
Answers: "Why are we building this product?"

Produces a comprehensive, enterprise-scale BRD (executive summary through
glossary — 40 sections) rather than a short summary. In MOCK mode this is
assembled deterministically from content_kit's module library so it stays
internally consistent with the User Stories, PRD, and UX documents that
follow it in the pipeline.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402
import content_kit as ck  # noqa: E402


class BusinessAnalystAgent(BaseAgent):
    role = AgentRole.BUSINESS_ANALYST
    max_output_tokens = 8000

    def build_prompt(self, context: ProjectContext) -> str:
        answered = "\n".join(f"- {q.text} -> {q.answer}" for q in context.discovery_questions if q.answer)
        return f"""{self.resolution_notes_block(context)}You are a senior business analyst producing a
comprehensive, enterprise-grade Business Requirements Document (BRD) —
the kind of document that runs 60-80 pages in Word, not a 3-page summary.
This document will be read by other AI agents downstream (not just
humans), so it must be specific, structured, and self-contained. Go deep,
not just broad: every list should be as long as the actual product
warrants, not capped at 2-3 illustrative examples.

Business idea: "{context.business_idea_raw}"
Domain: {context.domain_classification}

Answered discovery questions:
{answered}

Write ALL of the following sections, covering: executive summary;
business background; a problem-statement table (problem area / pain
point / business impact) covering every relevant problem, not just 2-3;
product vision; business objectives; a goals/KPI table (KPI / definition
/ target / measurement method — mark unknown targets TBD, never invent
an authoritative number); scope (in/out/non-goals); a stakeholder table;
user roles & permissions (purpose, responsibilities, capabilities,
permissions, restrictions per role, plus a role/permission table);
detailed user personas; current-state process narrative; future-state
process narrative; user journeys per major role; a product modules table
(module ID / name / purpose); a full functional-requirements list with
IDs FR-001, FR-002, ... (name, description, primary actor, priority) —
do not artificially limit the count, cover every module in real depth;
a detailed module-by-module breakdown (purpose, actors, inputs,
processing, outputs, business rules, dependencies, priority) for every
module; a business-rules table with IDs BR-001, BR-002, ...; a
non-functional-requirements table with IDs NFR-001, NFR-002, ... across
performance/scalability/availability/reliability/security/privacy/
accessibility/usability/maintainability/compatibility/monitoring/
logging/backup/disaster-recovery/localization; a data-requirements
section (entities and key fields, plus relationships); a data
classification section (public/internal/confidential/restricted); a
notifications matrix (event / customer / provider / admin / channel); a
payments section if relevant; an admin & operations section; a
reporting & analytics section (report groups plus key analytics events);
a security requirements section including a threats table; a privacy &
compliance section (state explicitly that applicable regulation must be
confirmed for the launch geography if unknown — never invent a
compliance claim); an accessibility section (target WCAG 2.2 AA unless
told otherwise); an integrations table; assumptions; constraints;
dependencies; a risks table (risk / impact / consequence / mitigation);
an MVP prioritization table (P0/P1/P2/P3/Out of scope); user stories
derived from the functional requirements (ID, title, actor, story,
priority, related FR); Given/When/Then acceptance criteria for the major
capabilities; a full traceability matrix (BRD area / FR / user story /
module / QA reference / priority); a phased release strategy with exit
criteria per phase; future enhancements explicitly deferred from MVP;
and a glossary of terms.

Rules:
- Assign each functional requirement a unique ID: FR-001, FR-002, ...
- Assign each business rule a unique ID: BR-001, BR-002, ...
- Assign each NFR a unique ID: NFR-001, NFR-002, ...
- Assign each user story a unique ID: US-001, US-002, ...
- Do not invent unsupported business information, compliance claims, or
  authoritative KPI targets. If something is unknown, explicitly mark it
  TBD or as an assumption/open question rather than guessing.
- Every list should be as complete as the actual product needs — do not
  artificially cap requirements, rules, or risks at a token few examples.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "executive_summary": {{"product": "...", "target_users": "...", "opportunity": "...", "solution": "...", "business_value": "...", "capabilities": ["...", "..."]}},
  "business_background": {{"current_context": "...", "existing_process": "...", "market_situation": "...", "why_needed": "...", "current_limitations": "...", "business_opportunity": "..."}},
  "problem_statement": [{{"area": "...", "pain_point": "...", "impact": "..."}}],
  "product_vision": {{"vision": "...", "future_state": "...", "long_term_direction": "...", "value_proposition": "..."}},
  "business_objectives": ["...", "..."],
  "kpis": [{{"kpi": "...", "definition": "...", "target": "... or TBD", "measurement": "..."}}],
  "scope_in": ["...", "..."], "scope_out": ["...", "..."], "non_goals": ["...", "..."],
  "stakeholders": [{{"stakeholder": "...", "interest": "...", "authority": "..."}}],
  "roles": [{{"role": "...", "purpose": "...", "responsibilities": "...", "capabilities": "...", "permissions": "...", "restricted": "..."}}],
  "user_personas": [{{"name": "...", "role": "...", "occupation": "...", "goals": "...", "needs": "...", "pain_points": "...", "behaviors": "...", "expectations": "..."}}],
  "current_state_process": "...", "current_state_flow": "Step 1 -> Step 2 -> ...",
  "future_state_process": "...", "future_state_flow": "Step 1 -> Step 2 -> ...",
  "user_journeys": {{"Customer Journey": "...", "Provider Journey": "...", "Admin Journey": "..."}},
  "modules": [{{"id": "MOD-01", "name": "...", "purpose": "..."}}],
  "requirements": [{{"id": "FR-001", "name": "...", "description": "...", "actor": "...", "priority": "P0|P1|P2|P3", "module": "..."}}],
  "module_details": [{{"module": "...", "purpose": "...", "actors": "...", "inputs": "...", "processing": "...", "outputs": "...", "business_rules": "...", "dependencies": "...", "priority": "..."}}],
  "business_rules": [{{"id": "BR-001", "rule": "...", "module": "..."}}],
  "nfrs": [{{"id": "NFR-001", "category": "...", "requirement": "...", "priority": "..."}}],
  "data_entities": [{{"entity": "...", "fields": ["...", "..."]}}],
  "data_relationships": ["...", "..."],
  "data_classification": [{{"level": "Public|Internal|Confidential|Restricted", "examples": "...", "access": "..."}}],
  "notifications_matrix": [{{"event": "...", "customer": "Yes|No", "provider": "Yes|No", "admin": "Yes|No", "channel": "..."}}],
  "payment_requirements": {{"methods": "...", "flow": "...", "statuses": "...", "failure_retry": "...", "duplicate_prevention": "...", "refunds": "...", "reconciliation": "..."}},
  "admin_operations": {{"dashboard": "...", "user_management": "...", "content_management": "...", "configuration": "...", "audit": "..."}},
  "reporting": [{{"group": "...", "reports": ["...", "..."]}}],
  "analytics_events": ["...", "..."],
  "security_requirements": ["...", "..."],
  "threats": [{{"threat": "...", "control": "..."}}],
  "privacy_compliance": "...",
  "accessibility": ["...", "..."],
  "integrations": [{{"integration": "...", "purpose": "...", "requirements": "..."}}],
  "assumptions": ["...", "..."], "constraints": ["...", "..."], "dependencies": ["...", "..."],
  "risks": [{{"risk": "...", "impact": "...", "consequence": "...", "mitigation": "..."}}],
  "mvp_prioritization": {{"P0": ["..."], "P1": ["..."], "P2": ["..."], "P3": ["..."], "out_of_scope": ["..."]}},
  "user_stories_summary": [{{"id": "US-001", "title": "...", "actor": "...", "story": "...", "priority": "...", "related_fr": "FR-001"}}],
  "acceptance_criteria_summary": [{{"capability": "...", "criteria": ["Given ..., when ..., then ...", "..."]}}],
  "traceability_matrix": [{{"brd_area": "...", "fr": "FR-001", "user_story": "US-001", "module": "...", "qa_reference": "QA-001", "priority": "..."}}],
  "release_strategy": [{{"phase": "...", "description": "...", "exit_criteria": "..."}}],
  "future_enhancements": ["...", "..."],
  "glossary": [{{"term": "...", "definition": "..."}}]
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        answers = {q.id: q.answer for q in context.discovery_questions if q.answer}
        domain_readable = ck.domain_readable(context)
        # Avoid "booking platform platform" when the domain name already
        # ends in "platform"; otherwise append it for a natural phrase.
        platform_phrase = domain_readable if domain_readable.endswith("platform") else f"{domain_readable} platform"
        target_users = ck.target_users_phrase(context)
        vocab = ck.get_vocab(context.domain_classification)
        answers_text = " ".join(str(v) for v in answers.values()).lower()

        modules = ck.select_modules(context)
        has_payments = any(m["key"] == "payments" for m in modules) or "payment" in answers_text
        requirements = ck.build_functional_requirements(modules)
        business_rules = ck.build_business_rules(modules)
        nfrs = ck.build_nfrs()
        entities, relationships = ck.build_data_model(modules, context)
        notifications = ck.build_notifications_matrix(modules, context)
        personas = ck.build_personas(context)
        stakeholders = ck.build_stakeholders()
        roles = ck.build_roles(modules, context)
        risks = ck.build_risks()
        glossary = ck.build_glossary(modules, context)
        integrations = ck.build_integrations(modules, context)
        stories = ck.build_stories(requirements, modules, context)

        module_id_map = {m["key"]: f"MOD-{i:02d}" for i, m in enumerate(modules, start=1)}
        product_modules = [{"id": module_id_map[m["key"]], "name": m["name"], "purpose": m["purpose"]} for m in modules]

        module_details = [{
            "module": m["name"], "purpose": m["purpose"], "actors": ", ".join(m["actors"]),
            "inputs": ", ".join(m["inputs"]), "processing": " -> ".join(m["processing"]),
            "outputs": ", ".join(m["outputs"]), "business_rules": "; ".join(m["business_rules"]),
            "dependencies": "None" if m["key"] == "authentication" else "Authentication",
            "priority": m["fr"][0]["priority"] if m["fr"] else "P1",
        } for m in modules]

        problem_statement = [
            {"area": "Discovery", "pain_point": f"{target_users} have no dedicated, reliable way to find the right {vocab['item'].lower()} today.", "impact": "Lost time, inconsistent outcomes, and missed opportunities on both sides of the transaction."},
            {"area": "Coordination", "pain_point": f"Arranging a {vocab['transaction'].lower()} currently relies on manual, ad-hoc communication.", "impact": "Slower turnaround, higher error rate, and a poor experience that erodes trust."},
            {"area": "Trust & Transparency", "pain_point": "There is no consistent way to verify quality or track status once a commitment is made.", "impact": "Users hesitate to commit, depressing conversion and repeat usage."},
        ]
        if has_payments:
            problem_statement.append({"area": "Payments", "pain_point": "Payment handling today is manual or fragmented across tools.", "impact": "Delayed payment, reconciliation errors, and disputes that consume operational time."})

        kpis = [
            {"kpi": "Conversion rate", "definition": f"Share of {vocab['buyer'].lower()}s who complete a {vocab['transaction'].lower()} after starting one", "target": "TBD", "measurement": "Completed / started transactions"},
            {"kpi": "Completion rate", "definition": f"Share of confirmed {vocab['transaction'].lower()}s that reach a completed state", "target": "TBD", "measurement": f"Completed / confirmed {vocab['transaction'].lower()}s"},
            {"kpi": "Customer satisfaction", "definition": "Post-transaction satisfaction score", "target": "TBD", "measurement": "Average review rating / survey score"},
            {"kpi": "Retention", "definition": f"Share of {vocab['buyer'].lower()}s who return for a second {vocab['transaction'].lower()} within 90 days", "target": "TBD", "measurement": "Repeat-user cohort analysis"},
            {"kpi": "Revenue", "definition": "Total platform revenue from completed transactions", "target": "TBD", "measurement": "Sum of captured payments, net of refunds"},
            {"kpi": "Processing time", "definition": f"Time from {vocab['transaction'].lower()} creation to confirmation", "target": "TBD", "measurement": "Timestamp delta, averaged"},
            {"kpi": "Error rate", "definition": "Share of transactions that fail or error before completion", "target": "TBD", "measurement": "Failed / attempted transactions"},
            {"kpi": "Support resolution time", "definition": "Time from ticket creation to resolution", "target": "TBD", "measurement": "Timestamp delta, averaged per ticket"},
        ]
        if any(m["key"] == "provider_management" for m in modules):
            kpis.append({"kpi": f"{vocab['seller']} utilization", "definition": f"Share of available {vocab['seller'].lower()} capacity actually booked", "target": "TBD", "measurement": f"Booked / available {vocab['seller'].lower()} slots"})

        current_flow = f"{vocab['buyer']} -> Contact {vocab['seller']} manually -> Discuss details -> Check availability -> Confirm informally -> Arrange payment -> {vocab['transaction']} happens"
        future_flow = f"{vocab['buyer']} -> Browse/Search -> Select {vocab['item']} -> Select details -> Review -> Pay -> Confirmation -> {vocab['seller']} assignment -> {vocab['transaction']} -> Review"

        journeys = {f"{vocab['buyer']} Journey": f"{vocab['buyer']} discovers the platform, searches for a {vocab['item'].lower()}, reviews options, completes a {vocab['transaction'].lower()}, and leaves a review after completion."}
        if any(m["key"] == "provider_management" for m in modules):
            journeys[f"{vocab['seller']} Journey"] = f"{vocab['seller']} applies to join, is verified, publishes {vocab['item'].lower()}s, manages incoming {vocab['transaction'].lower()}s, and gets paid."
        journeys["Admin/Operations Journey"] = f"Admin monitors the exception queue, moderates flagged {vocab['item'].lower()}s, resolves disputes, and reviews operational reports."
        journeys["Support Journey"] = "Support agent receives a ticket, reviews the linked account/transaction context, resolves or escalates, and closes with a resolution note."

        mvp = {"P0": [], "P1": [], "P2": [], "P3": []}
        for r in requirements:
            mvp[r["priority"]].append(f"{r['id']} — {r['name']}")
        mvp_out = ["Advanced analytics/reporting beyond the core report groups (future phase)",
                   "Multi-region/multi-currency support (future phase)",
                   "AI-assisted recommendations or matching (future phase)"]

        acceptance_summary = []
        for m in modules[:6]:
            first_fr = m["fr"][0] if m["fr"] else None
            if not first_fr:
                continue
            matching_story = next((s for s in stories if s["feature"] == first_fr["name"]), None)
            if matching_story:
                acceptance_summary.append({"capability": first_fr["name"], "criteria": matching_story["acceptance_criteria"]})

        traceability = []
        story_by_fr = {s["related_fr_ids"][0]: s for s in stories if s.get("related_fr_ids")}
        for i, r in enumerate(requirements, start=1):
            story = story_by_fr.get(r["id"])
            traceability.append({
                "brd_area": r["module"], "fr": r["id"], "user_story": story["id"] if story else "N/A",
                "module": r["module"], "qa_reference": f"QA-{i:03d}", "priority": r["priority"],
            })

        release_strategy = [
            {"phase": "Phase 0 — Discovery", "description": "Finalize requirements, policies, and architecture decisions.", "exit_criteria": "BRD, PRD, and UX specification reviewed and approved by stakeholders."},
            {"phase": "Phase 1 — MVP", "description": f"Deliver the P0/P1 functionality needed for a usable {domain_readable} product.", "exit_criteria": "All P0 requirements implemented and passing QA; core flow demonstrable end-to-end."},
            {"phase": "Phase 1.1 — Stabilization", "description": "Bug fixes, usability refinements, accessibility and performance hardening.", "exit_criteria": "No open P0/P1 defects; NFR targets met or explicitly deferred with sign-off."},
            {"phase": "Phase 2 — Expansion", "description": "P2/P3 functionality and the future enhancements listed in this document.", "exit_criteria": "Prioritized backlog re-evaluated against post-launch metrics."},
        ]

        future_enhancements = ["AI-assisted recommendations/matching", "Dynamic pricing", "Loyalty/rewards program", "Predictive analytics for demand/supply balancing"]
        if any(m["key"] == "support" for m in modules):
            future_enhancements.append("AI-assisted customer support (chatbot triage)")
        if any(m["key"] == "provider_management" for m in modules):
            future_enhancements.append(f"Subscription tiers for {vocab['seller'].lower()}s")

        return {
            "summary": f"Business analysis for a {domain_readable} idea covering {len(modules)} product modules, {len(requirements)} functional requirements, and {len(business_rules)} business rules, based on {len(answers)} answered discovery questions.",
            "executive_summary": {
                "product": context.business_idea_raw,
                "target_users": target_users,
                "opportunity": f"{target_users} currently lack a dedicated, reliable way to complete the {vocab['transaction'].lower()} workflow this product addresses.",
                "solution": f"A {platform_phrase} that lets {vocab['buyer'].lower()}s discover, commit to, and track a {vocab['item'].lower()} end-to-end, replacing manual coordination with a structured digital workflow.",
                "business_value": f"Faster, more reliable {vocab['transaction'].lower()}s increase conversion and repeat usage while reducing the manual operational burden of running the business.",
                "capabilities": [m["name"] for m in modules],
            },
            "business_background": {
                "current_context": f"Today, the {vocab['transaction'].lower()} workflow described in the business idea is handled manually or through disconnected, general-purpose tools.",
                "existing_process": current_flow,
                "market_situation": f"The {domain_readable} space rewards platforms that reduce friction and build trust between {vocab['buyer'].lower()} and {vocab['seller'].lower()}.",
                "why_needed": f"Without a dedicated product, {target_users} face avoidable friction, and the business cannot scale beyond what manual coordination allows.",
                "current_limitations": "No structured record of transactions, no built-in trust mechanisms, and no operational visibility into what is happening across the business.",
                "business_opportunity": f"A purpose-built platform can capture the {domain_readable} workflow digitally, creating a defensible, scalable business.",
            },
            "problem_statement": problem_statement,
            "product_vision": {
                "vision": f"Become the default way {target_users} handle the {vocab['transaction'].lower()} workflow described in the business idea.",
                "future_state": f"{vocab['buyer']}s and {vocab['seller']}s transact through a single trusted platform with full visibility into status at every step.",
                "long_term_direction": "Expand from the core MVP workflow into the future enhancements identified in this document as usage and data mature.",
                "value_proposition": f"Faster, more trustworthy {vocab['transaction'].lower()}s than the manual alternative, with less operational overhead for the business running the platform.",
            },
            "business_objectives": [
                f"Validate the core {vocab['transaction'].lower()} workflow with early {target_users}",
                "Reduce the manual operational work required to run the business",
                f"Increase transparency for {vocab['buyer'].lower()}s and {vocab['seller'].lower()}s throughout a {vocab['transaction'].lower()}",
                "Reach initial operational and financial viability for the MVP scope",
            ],
            "kpis": kpis,
            "scope_in": [f"Core {domain_readable} workflow: {', '.join(m['name'] for m in modules[:6])}", "Basic user onboarding and account management"],
            "scope_out": ["Advanced analytics/reporting beyond the core report groups (future phase)", "Multi-region/multi-currency support (future phase)"],
            "non_goals": ["Building a general-purpose platform beyond the described domain", "Replacing every internal operational tool on day one"],
            "stakeholders": stakeholders,
            "roles": roles,
            "user_personas": personas,
            "current_state_process": f"Today, a {vocab['transaction'].lower()} is arranged manually: the {vocab['buyer'].lower()} contacts a {vocab['seller'].lower()} directly, they discuss details informally, check availability back and forth, confirm verbally or in writing, and arrange payment separately from the {vocab['transaction'].lower()} itself. There is no shared source of truth for either party.",
            "current_state_flow": current_flow,
            "future_state_process": f"The proposed platform replaces ad-hoc coordination with a structured flow: the {vocab['buyer'].lower()} browses or searches, selects a {vocab['item'].lower()} and the relevant details, reviews the total cost, pays, and receives confirmation — with the {vocab['seller'].lower()} notified and assigned automatically. Alternative and failure paths (payment failure, unavailable slot, cancellation) are handled explicitly rather than left to manual follow-up.",
            "future_state_flow": future_flow,
            "user_journeys": journeys,
            "modules": product_modules,
            "requirements": requirements,
            "module_details": module_details,
            "business_rules": business_rules,
            "nfrs": nfrs,
            "data_entities": entities,
            "data_relationships": relationships,
            "data_classification": [
                {"level": "Public", "examples": f"Published {vocab['item'].lower()} listings, aggregate ratings", "access": "No authentication required"},
                {"level": "Internal", "examples": "Operational reports, internal notes", "access": "Authenticated staff roles only"},
                {"level": "Confidential", "examples": "Account contact details, transaction history", "access": "Record owner and authorized staff only"},
                {"level": "Restricted", "examples": "Payment credentials, identity verification documents", "access": "System/processor only; never exposed directly, even to Admin"},
            ],
            "notifications_matrix": notifications,
            "payment_requirements": ({
                "methods": "TBD — specific payment methods to be confirmed; commonly cards and/or digital wallets",
                "flow": f"{vocab['buyer']} confirms {vocab['transaction'].lower()} -> payment captured -> {vocab['transaction'].lower()} confirmed -> funds reconciled",
                "statuses": "Pending, Captured, Failed, Refunded, Partially Refunded",
                "failure_retry": "Buyer may retry with the same or a different method without duplicating the transaction",
                "duplicate_prevention": "A single confirmation action results in at most one successful charge",
                "refunds": "Full or partial refunds follow the active cancellation policy and are recorded against the original payment",
                "reconciliation": "Internal transaction records must reconcile against processor records on a regular schedule",
            } if has_payments else None),
            "admin_operations": {
                "dashboard": "At-a-glance view of active transactions, exceptions, and recent activity",
                "user_management": f"Search, view, and manage {vocab['buyer'].lower()} and {vocab['seller'].lower()} accounts",
                "content_management": f"Moderate {vocab['item'].lower()} listings and reviews",
                "configuration": "Manage platform-level configuration (policies, categories) where applicable",
                "audit": "Append-only audit log of every administrative action",
            },
            "reporting": [
                {"group": "Operations", "reports": [f"{vocab['transaction']} volume", "Exception queue summary"]},
                ({"group": "Finance", "reports": ["Revenue report", "Refund report", "Reconciliation report"]} if has_payments
                 else {"group": "Finance", "reports": ["TBD — dependent on business model finalization"]}),
                {"group": "Customer", "reports": [f"{vocab['buyer']} acquisition", f"{vocab['buyer']} retention"]},
                ({"group": "Provider", "reports": [f"{vocab['seller']} performance"]} if any(m["key"] == "provider_management" for m in modules)
                 else {"group": "Product", "reports": [f"{vocab['item']} performance"]}),
                {"group": "Support", "reports": ["Ticket volume and resolution time"]},
            ],
            "analytics_events": [e for e in [
                f"{vocab['item'].lower()}_viewed", f"{vocab['transaction'].lower()}_started", "payment_started" if has_payments else None,
                "payment_succeeded" if has_payments else None, f"{vocab['transaction'].lower()}_confirmed",
                f"{vocab['transaction'].lower()}_cancelled", f"{vocab['transaction'].lower()}_completed", "review_submitted",
            ] if e],
            "security_requirements": next((m["business_rules"] for m in modules if m["key"] == "security"), []) + [
                "All state-changing actions require server-side permission checks, independent of client UI.",
            ],
            "threats": [
                {"threat": "Credential stuffing / brute-force login", "control": "Rate limiting and account lockout after repeated failures"},
                {"threat": "Payment fraud", "control": "Tokenized payment handling via a PCI-compliant processor; anomaly monitoring"},
                {"threat": "Data exposure via broken access control", "control": "Server-side role-based access control on every endpoint"},
                {"threat": "Fake/duplicate accounts", "control": "Identifier verification and duplicate-account detection at registration"},
            ],
            "privacy_compliance": "Applicable privacy and regulatory requirements must be confirmed for the launch geography. In the interim, personal data should be minimized, encrypted at rest, and access-logged, with deletion honored on request.",
            "accessibility": [
                "Target WCAG 2.2 AA across primary user flows unless the business context specifies another standard.",
                "All interactive elements must be reachable and operable via keyboard.",
                "Form fields must have accessible labels and clear, non-color-only error indication.",
            ],
            "integrations": integrations,
            "assumptions": [
                f"ASSUMPTION: {target_users} have internet-connected devices.",
                "ASSUMPTION: Initial launch targets a single geography.",
                ("ASSUMPTION: A payment processor will be available and integrated for MVP." if has_payments
                 else "ASSUMPTION: No payment processing is required for the MVP scope as currently understood."),
            ],
            "constraints": [
                "POC/MVP scope — not yet designed for production scale.",
                "Timeline and budget constraints: TBD.",
                "Regulatory constraints: TBD pending confirmation of launch geography.",
            ],
            "dependencies": [d["integration"] for d in integrations] + ["Legal/compliance review prior to launch"],
            "risks": risks,
            "mvp_prioritization": {**mvp, "out_of_scope": mvp_out},
            "user_stories_summary": [
                {"id": s["id"], "title": s["feature"], "actor": s["role"], "story": s["story"],
                 "priority": next((r["priority"] for r in requirements if r["id"] == s["related_fr_ids"][0]), "P2"),
                 "related_fr": s["related_fr_ids"][0]}
                for s in stories
            ],
            "acceptance_criteria_summary": acceptance_summary,
            "traceability_matrix": traceability,
            "release_strategy": release_strategy,
            "future_enhancements": future_enhancements,
            "glossary": glossary,
            "open_questions": (
                [f"{q.text} — left unanswered by the user; treat as an open question requiring follow-up." for q in context.discovery_questions if q.status.value in ("pending", "skipped")]
                or ["None outstanding — all discovery questions were answered"]
            ),
            # Kept for backward compatibility with earlier/simpler consumers
            # (older export/template code, other agents' prompts, etc.).
            "project_overview": context.business_idea_raw,
            "problem_statement_text": f"{target_users} need a better way to accomplish the goal described in: \"{context.business_idea_raw}\"",
            "target_users": target_users,
            "user_pain_points": [p["pain_point"] for p in problem_statement],
            "expected_business_outcomes": [f"Increased efficiency for {target_users} in the core workflow", "A validated foundation to expand feature scope in later phases"],
            "success_metrics": [k["kpi"] for k in kpis],
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

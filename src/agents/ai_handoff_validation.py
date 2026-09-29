"""
AI Handoff Validation Agent -> AI Handoff Validation Report
Answers: "Are these five documents complete, consistent, and ready to be
consumed by the external Design AI Agent?"

This is a VALIDATION document, not another product specification. Runs
last — reads all 4 other documents and checks:
  1. Document completeness (each of the 4 docs individually)
  2. Cross-document consistency (BRD<->Stories<->PRD<->UX, requirements
     <->screens, roles/permissions<->UX, technical/security constraints
     <->PRD/UX)
  3. Design readiness — is there enough info about users, flows, screens,
     states, forms, permissions, etc. for a Design AI Agent to work from?

Produces a final status of exactly one of:
  READY FOR DESIGN AGENT / READY WITH WARNINGS / NOT READY FOR DESIGN AGENT
This must reflect actual completeness — never auto-return READY.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentContribution, AgentRole, ProjectContext  # noqa: E402
import coverage as cov  # noqa: E402

REQUIRED_ROLES = [
    AgentRole.BUSINESS_ANALYST,
    AgentRole.PRODUCT_MANAGER,
    AgentRole.PRODUCT_REQUIREMENTS,
    AgentRole.UX_PRODUCT_FLOW,
]


class AIHandoffValidationAgent(BaseAgent):
    role = AgentRole.AI_HANDOFF_VALIDATION
    max_output_tokens = 8000

    @staticmethod
    def _digest(context: ProjectContext) -> str:
        """A compact, structured digest of the four documents for the LLM
        validator. Dumping every document's raw output (76 FRs, 76 stories,
        32 screens, 76 flows...) buries the signal in >100k tokens that a
        lite model can't review; the structural facts it needs — names, IDs,
        roles, scope, navigation — fit in a few thousand."""
        get = lambda role: (context.get_contribution(role).output if context.get_contribution(role) else {})
        ba, pm, prd, ux = (get(AgentRole.BUSINESS_ANALYST), get(AgentRole.PRODUCT_MANAGER),
                           get(AgentRole.PRODUCT_REQUIREMENTS), get(AgentRole.UX_PRODUCT_FLOW))
        if not any((ba.get("requirements"), pm.get("stories"))):
            # small/legacy outputs: fall back to the raw dump
            return "\n\n".join(f"--- {c.agent.value} ---\n{c.output}" for c in context.agent_contributions)
        frs_by_mod = {}
        for r in ba.get("requirements", []):
            frs_by_mod.setdefault(r.get("module"), []).append(f"{r['id']} {r['name']} ({r.get('priority')}, actor {r.get('actor')})")
        lines = ["--- BUSINESS REQUIREMENTS (digest) ---",
                 f"Target users: {ba.get('target_users', '')}",
                 "Roles: " + "; ".join(f"{r.get('role')}: {str(r.get('restricted', ''))[:140]}" for r in ba.get("roles", [])),
                 "Glossary terms: " + ", ".join(g.get("term", "") for g in ba.get("glossary", []) if isinstance(g, dict)),
                 f"Modules ({len(ba.get('modules', []))}) and their requirements:"]
        for m in ba.get("modules", []):
            lines.append(f"  {m['id']} {m['name']}: " + "; ".join(frs_by_mod.get(m["name"], [])))
        lines.append("Business rules: " + " | ".join(f"{b['id']}: {b['rule'][:110]}" for b in ba.get("business_rules", [])))
        lines.append("MVP prioritization counts: " + ", ".join(f"{k}={len(v)}" for k, v in (ba.get("mvp_prioritization") or {}).items()))
        lines += ["", "--- USER STORIES (digest) ---",
                  f"{len(pm.get('stories', []))} stories, {len(pm.get('epics', []))} epics. Epics: " + "; ".join(e["name"] for e in pm.get("epics", [])),
                  "Story roles: " + ", ".join(sorted({s.get("role", "") for s in pm.get("stories", [])}))]
        lines += ["", "--- PRD (digest) ---",
                  f"Overview: {str(prd.get('product_overview', ''))[:400]}",
                  f"Target users: {prd.get('target_users', '')}",
                  "Roles & permissions: " + " | ".join(f"{r['role']}: {', '.join(r.get('permissions', []))[:220]}" for r in prd.get("roles_and_permissions", [])),
                  f"Navigation pattern: {prd.get('navigation_pattern', '')} — {prd.get('navigation_behavior', '')}",
                  f"Scope: MVP={len(prd.get('mvp_scope', []))} FRs, Phase 2={len(prd.get('phase_2_scope', []))}, Future={len(prd.get('future_scope', []))}",
                  f"Detailed FR entries: {len(prd.get('functional_requirements', []))}"]
        lines += ["", "--- UX / PRODUCT FLOW (digest) ---",
                  f"Navigation: {(ux.get('navigation') or {}).get('pattern', '')} — {str((ux.get('navigation') or {}).get('structure', ''))[:500]}",
                  f"{len(ux.get('screens', []))} screens, {len(ux.get('user_flows', []))} flows, {len(ux.get('screen_states', []))} states, "
                  f"{len(ux.get('interactions', []))} interactions, {len(ux.get('forms', []))} forms",
                  "Screens: " + "; ".join(f"{s['id']} {s['name']} [{s.get('primary_role', '')}]" for s in ux.get("screens", [])),
                  "UX roles: " + ", ".join(r.get("role", "") for r in ux.get("roles_permissions_matrix", []))]
        return "\n".join(lines)

    @staticmethod
    def depth_findings(context: ProjectContext) -> list[dict]:
        """Deterministic structural checks the LLM can't be trusted to notice
        (same idea as the coverage matrix): each finding is a missing_information
        entry naming exact IDs, so the resolve loop can regenerate exactly the
        implicated items. Live mode only — mock output is complete by construction."""
        get = lambda role: (context.get_contribution(role).output if context.get_contribution(role) else {})
        ba, pm, ux, prd = (get(AgentRole.BUSINESS_ANALYST), get(AgentRole.PRODUCT_MANAGER),
                           get(AgentRole.UX_PRODUCT_FLOW), get(AgentRole.PRODUCT_REQUIREMENTS))
        findings = []
        if not ba.get("requirements"):
            return findings
        docs = "UX / Product Flow Specification"
        flow_frs = {f for fl in ux.get("user_flows", []) for f in fl.get("related_requirement_ids", [])}
        no_flow = [r["id"] for r in ba["requirements"] if r["id"] not in flow_frs]
        if no_flow:
            findings.append({"missing_item": f"No user flow for requirement(s) {', '.join(no_flow[:25])}",
                             "affected_document": docs,
                             "impact_on_design_generation": "The Design AI Agent has no path to design for these requirements.",
                             "recommended_action": f"Add a user flow for each of: {', '.join(no_flow)}."})
        state_screens = {st.get("screen_id") for st in ux.get("screen_states", [])}
        no_state = [s["id"] for s in ux.get("screens", []) if s["id"] not in state_screens]
        if no_state:
            findings.append({"missing_item": f"No screen states for screen(s) {', '.join(no_state[:25])}",
                             "affected_document": docs,
                             "impact_on_design_generation": "Loading/empty/success/failure states would be improvised.",
                             "recommended_action": f"Define loading, empty, success and failure states for: {', '.join(no_state)}."})
        screen_text = " ".join(" ".join(s.get("business_rules", [])) for s in ux.get("screens", [])) + \
                      " ".join(" ".join(fl.get("decision_points", []) + fl.get("error_paths", [])) for fl in ux.get("user_flows", []))
        untraced = [b["id"] for b in ba.get("business_rules", []) if b["id"] not in screen_text]
        if untraced:
            findings.append({"missing_item": f"Business rule(s) {', '.join(untraced[:25])} are not enforced on any screen or flow",
                             "affected_document": docs,
                             "impact_on_design_generation": "The rule has no interface enforcement point.",
                             "recommended_action": f"Add the enforcing screen business_rules entry or flow decision point for: {', '.join(untraced)}."})
        ba_roles = {r.get("role") for r in ba.get("roles", [])}
        ux_roles = {r.get("role") for r in ux.get("roles_permissions_matrix", [])}
        prd_roles = {r.get("role") for r in prd.get("roles_and_permissions", [])}
        bad = sorted((ux_roles | prd_roles) - ba_roles)
        if bad:
            findings.append({"missing_item": f"Role name(s) {', '.join(bad)} do not match the Business Requirements roles ({', '.join(sorted(ba_roles))})",
                             "affected_document": "Product Requirements Document",
                             "impact_on_design_generation": "Role labels would differ between documents.",
                             "recommended_action": "Use the exact role names defined in the Business Requirements."})
        story_frs = {f for s in pm.get("stories", []) for f in s.get("related_fr_ids", [])}
        no_story = [r["id"] for r in ba["requirements"] if r["id"] not in story_frs]
        if no_story:
            findings.append({"missing_item": f"No user story for requirement(s) {', '.join(no_story[:25])}",
                             "affected_document": "User Stories",
                             "impact_on_design_generation": "Requirements without stories cannot be traced to screens.",
                             "recommended_action": f"Write a user story for each of: {', '.join(no_story)}."})
        findings += AIHandoffValidationAgent._content_depth_findings(ba, pm)
        return findings

    @staticmethod
    def _content_depth_findings(ba: dict, pm: dict) -> list[dict]:
        """Depth checks the ID-level coverage matrix can't see: every user story must carry
        validation rules, error messages, an empty-state entry and edge cases; the BRD must
        carry flow diagrams, an assessed/owned risk register and key parameters."""
        findings = []
        stories = pm.get("stories", [])
        for label, key in (("data validation rules", "data_validation"), ("exact error messages", "error_messages"),
                           ("an empty-state entry (or 'Not applicable — reason')", "empty_states"),
                           ("edge cases", "edge_cases")):
            missing = [s["id"] for s in stories if not [x for x in (s.get(key) or []) if str(x).strip()]]
            if missing:
                findings.append({
                    "missing_item": f"User stories {', '.join(missing[:25])} have no {label}",
                    "affected_document": "User Stories",
                    "impact_on_design_generation": "QA and the Design AI would have to invent this behaviour.",
                    "recommended_action": f"Add {label} to each of: {', '.join(missing)}."})
        few_ac = [s["id"] for s in stories if len(s.get("acceptance_criteria") or []) < 4]
        if few_ac:
            findings.append({
                "missing_item": f"User stories {', '.join(few_ac[:25])} have fewer than 4 acceptance criteria",
                "affected_document": "User Stories",
                "impact_on_design_generation": "Happy path, validation, error, empty-state and edge cases are not all testable.",
                "recommended_action": f"Expand the acceptance criteria to cover validation, errors, empty state and edge cases for: {', '.join(few_ac)}."})
        brd = "Business Requirements Document"
        if len(ba.get("flow_diagrams") or []) < 2:
            findings.append({
                "missing_item": "The Business Requirements have fewer than 2 envisioned flow diagrams",
                "affected_document": brd,
                "impact_on_design_generation": "The intended end-to-end flows are not visualised.",
                "recommended_action": "Add flow_diagrams (Mermaid flowcharts) for the core journey, transaction flow and support/admin flow."})
        risks = ba.get("risks") or []
        unassessed = [r.get("risk", "")[:50] for r in risks if not r.get("score")]
        no_owner = [r.get("risk", "")[:50] for r in risks if not str(r.get("owner", "")).strip()]
        if unassessed or no_owner or len(risks) < 8:
            bits = []
            if unassessed:
                bits.append(f"{len(unassessed)} risk(s) lack a likelihood/severity assessment")
            if no_owner:
                bits.append(f"{len(no_owner)} risk(s) have no owner")
            if len(risks) < 8:
                bits.append(f"only {len(risks)} risks are listed")
            findings.append({
                "missing_item": "Risk register is incomplete: " + "; ".join(bits),
                "affected_document": brd,
                "impact_on_design_generation": "Risks cannot be ranked or acted on.",
                "recommended_action": "Revise the risks section: 10+ product-specific risks, each with likelihood, severity, owner, "
                                      "trigger and a concrete mitigation."})
        if len(ba.get("key_parameters") or []) < 8:
            findings.append({
                "missing_item": "Key business parameters (timeouts, windows, thresholds, limits) are missing or too few",
                "affected_document": brd,
                "impact_on_design_generation": "Vague rules such as 'a period of inactivity' cannot be designed or tested.",
                "recommended_action": "Add key_parameters: 12+ concrete values or explicit TBD decisions the requirements depend on."})
        return findings

    def build_prompt(self, context: ProjectContext) -> str:
        contributions_summary = self._digest(context)
        matrix = cov.compute_coverage_matrix(context)
        matrix_lines = "\n".join(
            f"- {r['capability']} [{', '.join(r['fr_ids']) or 'no FR ids'}]: "
            f"BRD={r['brd']} PRD={r['prd']} UserStory={r['user_story']} UX={r['ux']} "
            f"Technical={r['technical']} Security={r['security']}"
            + (f" — {'; '.join(r['notes'])}" if r["notes"] else "")
            for r in matrix["rows"]
        )
        unmapped_lines = "\n".join(f"- {c}" for c in matrix["unmapped_idea_capabilities"]) or "- None"

        return f"""You are validating a 5-document product specification
package before it is handed off to an INDEPENDENT, EXTERNAL Design AI
Agent that will generate UI/UX designs from these documents alone — it
will have no access to this conversation or any other context.

Your job is ONLY validation — do not write new requirements or new
product content, that already exists in the other 4 documents.

Business idea: "{context.business_idea_raw}"

{contributions_summary}

A DETERMINISTIC, CODE-COMPUTED capability coverage matrix has already been
built by matching requirement IDs across the four documents (this is
ground truth — do not recompute or contradict it, only add narrative
detail a mechanical ID match can't see, like terminology/navigation/role
mismatches):

{matrix_lines}

Capabilities the business idea/discovery answers clearly imply that have
NO module or requirement anywhere in the Business Requirements at all:
{unmapped_lines}

Totals: {matrix['totals']}

Check:
1. COMPLETENESS — is each of the 4 upstream documents (Business
   Requirements, User Stories, PRD, UX/Product Flow Specification)
   actually complete? Treat any ❌ or ⚠️ row above (that isn't N/A) as a
   real completeness gap — do not soften it.
2. CROSS-DOCUMENT CONSISTENCY — beyond the ID-level matrix above, look for
   narrative inconsistencies: different target users, different navigation
   or screen names for the same feature, conflicting role/permission
   names, conflicting business rules or MVP scope, or a user story mapped
   to an unrelated requirement (e.g. a registration story mapped to a
   banking/payment requirement).
3. DESIGN READINESS — is there enough detail on users, personas, roles,
   features, requirements, user journeys, flows, screens, screen states,
   interactions, forms, validation, error/empty/loading states, navigation,
   permissions, business rules, dependencies, and technical/security
   constraints affecting UX for an independent Design AI Agent to work
   from without needing anything else?

Be honest — do not automatically return "READY FOR DESIGN AGENT". If you
find real gaps or conflicts, say so and choose "READY WITH WARNINGS" or
"NOT READY FOR DESIGN AGENT" as appropriate.

CRITICAL CONSISTENCY RULE: final_handoff_status must agree with your own
conflicts_found and missing_information lists AND with the coverage matrix
above. If either list is non-empty, OR any matrix row has a ❌/⚠️ that
isn't N/A, OR any capability is listed as unmapped, final_handoff_status
CANNOT be "READY FOR DESIGN AGENT" — it must be at least "READY WITH
WARNINGS" (or "NOT READY FOR DESIGN AGENT" if the issues are numerous or
severe). Only return "READY FOR DESIGN AGENT" when there are truly no
gaps anywhere, including in the matrix.

Respond ONLY with JSON in exactly this shape:
{{
  "summary": "one sentence overview",
  "completeness_notes": ["...", "..."],
  "consistency_notes": ["...", "..."],
  "design_readiness_notes": ["...", "..."],
  "conflicts_found": [{{"id": "CONFLICT-001", "documents_involved": ["...", "..."], "conflicting_information": "...", "impact": "...", "recommended_resolution": "..."}}],
  "missing_information": [{{"missing_item": "...", "affected_document": "...", "impact_on_design_generation": "...", "recommended_action": "..."}}],
  "final_handoff_status": "READY FOR DESIGN AGENT" or "READY WITH WARNINGS" or "NOT READY FOR DESIGN AGENT",
  "recommendation": "..."
}}"""

    def mock_response(self, context: ProjectContext) -> dict:
        ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
        pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
        prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
        ux = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)

        completeness_notes = []
        conflicts = []
        missing = []
        conflict_n = 0

        # --- Completeness ---
        for role, label in [(AgentRole.BUSINESS_ANALYST, "Business Requirements"),
                             (AgentRole.PRODUCT_MANAGER, "User Stories"),
                             (AgentRole.PRODUCT_REQUIREMENTS, "PRD"),
                             (AgentRole.UX_PRODUCT_FLOW, "UX/Product Flow Specification")]:
            if context.get_contribution(role) is not None:
                completeness_notes.append(f"{label} document is present and populated.")
            else:
                missing.append({
                    "missing_item": f"{label} document",
                    "affected_document": label,
                    "impact_on_design_generation": "Design AI Agent would be missing a required input document entirely.",
                    "recommended_action": f"Re-run the pipeline to generate the {label} document.",
                })

        # --- Cross-document consistency checks (genuinely checkable in mock mode) ---
        consistency_notes = []

        if ba and pm:
            br_ids = {r.get("id") for r in ba.output.get("requirements", []) if isinstance(r, dict)}
            referenced_br_ids = set()
            for s in pm.output.get("stories", []):
                referenced_br_ids.update(s.get("related_fr_ids", []))
            unreferenced = br_ids - referenced_br_ids
            if unreferenced:
                conflict_n += 1
                conflicts.append({
                    "id": f"CONFLICT-{conflict_n:03d}",
                    "documents_involved": ["business_requirements", "user_stories"],
                    "conflicting_information": f"Business requirement(s) {sorted(unreferenced)} are not referenced by any user story.",
                    "impact": "The Design AI Agent may not realize these requirements need corresponding UI.",
                    "recommended_resolution": "Add a user story that explicitly maps to each unreferenced requirement.",
                })
            else:
                consistency_notes.append("Every business requirement is referenced by at least one user story.")

        if pm and prd:
            story_count = len(pm.output.get("stories", []))
            fr_count = len(prd.output.get("functional_requirements", []))
            if fr_count < story_count:
                conflict_n += 1
                conflicts.append({
                    "id": f"CONFLICT-{conflict_n:03d}",
                    "documents_involved": ["user_stories", "prd"],
                    "conflicting_information": f"{story_count} user stories exist but only {fr_count} functional requirements were derived in the PRD.",
                    "impact": "Some user-facing behavior may not be captured as a formal functional requirement.",
                    "recommended_resolution": "Ensure every user story has a corresponding FR-XXX entry in the PRD.",
                })
            else:
                consistency_notes.append(f"PRD functional requirements ({fr_count}) cover all {story_count} user stories.")

        if prd and ux:
            fr_ids = {fr.get("id") for fr in prd.output.get("functional_requirements", [])}
            referenced_fr_ids = set()
            for scr in ux.output.get("screens", []):
                referenced_fr_ids.update(scr.get("related_requirement_ids", []))
            for flow in ux.output.get("user_flows", []):
                referenced_fr_ids.update(flow.get("related_requirement_ids", []))
            unreferenced_fr = fr_ids - referenced_fr_ids
            if unreferenced_fr:
                conflict_n += 1
                conflicts.append({
                    "id": f"CONFLICT-{conflict_n:03d}",
                    "documents_involved": ["prd", "ux_product_flow_specification"],
                    "conflicting_information": f"Functional requirement(s) {sorted(unreferenced_fr)} are not linked to any screen or user flow.",
                    "impact": "The Design AI Agent has no screen to design for these requirements.",
                    "recommended_resolution": "Add a screen and/or user flow that fulfils each unreferenced functional requirement.",
                })
            else:
                consistency_notes.append("Every PRD functional requirement traces to at least one UX screen or flow.")

            prd_roles = {r.get("role") for r in prd.output.get("roles_and_permissions", [])}
            ux_roles = {r.get("role") for r in ux.output.get("roles_permissions_matrix", [])}
            if prd_roles != ux_roles and prd_roles and ux_roles:
                conflict_n += 1
                conflicts.append({
                    "id": f"CONFLICT-{conflict_n:03d}",
                    "documents_involved": ["prd", "ux_product_flow_specification"],
                    "conflicting_information": f"PRD roles {sorted(prd_roles)} do not exactly match UX roles/permissions matrix {sorted(ux_roles)}.",
                    "impact": "The Design AI Agent may design permission-gated UI inconsistently with the PRD's actual role model.",
                    "recommended_resolution": "Align the role names used in the PRD and the UX roles/permissions matrix.",
                })
            else:
                consistency_notes.append("PRD roles and UX roles/permissions matrix are aligned.")

        # --- Design readiness ---
        design_readiness_notes = []
        if ux:
            for field, label in [("screens", "screen inventory"), ("user_flows", "user flows"),
                                  ("screen_states", "screen states"), ("forms", "forms/validation"),
                                  ("navigation", "navigation"), ("roles_permissions_matrix", "roles/permissions")]:
                if ux.output.get(field):
                    design_readiness_notes.append(f"UX document includes {label}.")
                else:
                    missing.append({
                        "missing_item": label, "affected_document": "ux_product_flow_specification",
                        "impact_on_design_generation": f"Design AI Agent would lack {label}, which is needed to generate coherent designs.",
                        "recommended_action": f"Re-run the UX/Product Flow agent with more detailed inputs to populate {label}.",
                    })

        missing_whole_document = any(context.get_contribution(role) is None for role in REQUIRED_ROLES)

        # --- Deterministic capability coverage matrix (see coverage.py) ---
        # This is the authoritative completeness check — the checks above
        # remain as additional narrative detail, but every real gap must
        # also show up here or the matrix itself has a bug.
        matrix = cov.compute_coverage_matrix(context)
        for note in cov.gap_resolution_notes(matrix):
            missing.append({
                "missing_item": note,
                "affected_document": "business_requirements / prd / user_stories / ux_product_flow_specification",
                "impact_on_design_generation": "A capability that is not fully traceable end-to-end cannot be reliably designed for.",
                "recommended_action": "Re-run the affected agent(s) so this capability is fully represented in every downstream document.",
            })

        if missing_whole_document:
            status = "NOT READY FOR DESIGN AGENT"
        elif conflicts or missing or cov.matrix_has_blocking_gaps(matrix):
            total_issues = len(conflicts) + len(missing)
            status = "NOT READY FOR DESIGN AGENT" if total_issues > 2 else "READY WITH WARNINGS"
        else:
            status = "READY FOR DESIGN AGENT"

        return {
            "summary": f"Validated the 5-document package: {len(conflicts)} conflict(s), {len(missing)} missing item(s) found, {matrix['totals']['coverage_percentage']}% capability coverage.",
            "completeness_notes": completeness_notes,
            "consistency_notes": consistency_notes or ["No specific consistency notes generated."],
            "design_readiness_notes": design_readiness_notes,
            "conflicts_found": conflicts,
            "missing_information": missing,
            "coverage_matrix": matrix["rows"],
            "capability_summary": matrix["totals"],
            "missing_capabilities": matrix["missing_capabilities"],
            "partial_capabilities": matrix["partial_capabilities"],
            "unmapped_idea_capabilities": matrix["unmapped_idea_capabilities"],
            "final_handoff_status": status,
            "recommendation": (
                "Package is internally consistent and complete — ready to hand off to the Design AI Agent."
                if status == "READY FOR DESIGN AGENT" else
                "Resolve the flagged conflicts/gaps before treating this package as final."
                if status == "READY WITH WARNINGS" else
                "Significant gaps found — re-run the affected agent(s) before handing this package off."
            ),
        }

    def run(self, context: ProjectContext) -> AgentContribution:
        contribution = super().run(context)
        # Always attach the deterministic, code-computed coverage matrix —
        # even in LIVE mode, where the model was only asked to treat it as
        # ground truth in its prompt but can't be trusted to faithfully
        # transcribe it back into its own JSON output. Computing it here
        # (again) guarantees the matrix in the final artifact is always the
        # real one, never a model's paraphrase of it.
        matrix = cov.compute_coverage_matrix(context)
        import agents.base as _base
        if _base.get_client() is not None:
            existing = {m.get("missing_item") for m in contribution.output.get("missing_information", [])}
            for finding in self.depth_findings(context):
                if finding["missing_item"] not in existing:
                    contribution.output.setdefault("missing_information", []).append(finding)
        contribution.output["coverage_matrix"] = matrix["rows"]
        contribution.output["capability_summary"] = matrix["totals"]
        contribution.output["missing_capabilities"] = matrix["missing_capabilities"]
        contribution.output["partial_capabilities"] = matrix["partial_capabilities"]
        contribution.output["unmapped_idea_capabilities"] = matrix["unmapped_idea_capabilities"]

        self._enforce_status_consistency(contribution, matrix)
        # Reset rather than extend: this list reflects the CURRENT
        # validation state for display purposes. If we extended instead,
        # re-running validation during a "Resolve Issues" pass would show
        # stale notes about issues that were just fixed alongside the
        # fresh ones, which is actively misleading.
        context.consistency_notes = list(contribution.output.get("consistency_notes", []))
        for conflict in contribution.output.get("conflicts_found", []):
            context.consistency_notes.append(
                f"{conflict.get('id', 'CONFLICT')} [{', '.join(conflict.get('documents_involved', []))}]: {conflict.get('conflicting_information', '')}"
            )
        return contribution

    @staticmethod
    def _enforce_status_consistency(contribution: AgentContribution, matrix: dict) -> None:
        """Server-side guardrail on top of whatever final_handoff_status
        the model (LIVE mode) wrote — and, unconditionally, on top of the
        deterministic coverage matrix, which the model cannot talk its way
        around even if its own conflicts/missing lists are empty.

        The model is asked to keep final_handoff_status consistent with
        its own conflicts_found/missing_information lists (and with the
        matrix it was shown), but nothing stops it from writing "READY FOR
        DESIGN AGENT" anyway — LLM output isn't guaranteed self-consistent
        just because the prompt asked for it. MOCK mode already computes
        status deterministically from these same signals; this makes LIVE
        mode hold to the same invariant instead of trusting the model's
        own label at face value.
        """
        output = contribution.output
        issue_count = len(output.get("conflicts_found", [])) + len(output.get("missing_information", []))
        matrix_gap = cov.matrix_has_blocking_gaps(matrix)
        stated_status = output.get("final_handoff_status", "")

        if issue_count == 0 and not matrix_gap:
            return  # nothing to override — model's status stands either way

        minimum_status = "NOT READY FOR DESIGN AGENT" if (issue_count > 2 or matrix_gap) else "READY WITH WARNINGS"
        severity = {"READY FOR DESIGN AGENT": 0, "READY WITH WARNINGS": 1, "NOT READY FOR DESIGN AGENT": 2}
        if severity.get(stated_status, 0) < severity[minimum_status]:
            output["final_handoff_status"] = minimum_status
            reason = (
                f"{issue_count} conflict(s)/missing item(s)" if issue_count and not matrix_gap else
                "unresolved gaps in the deterministic capability coverage matrix" if matrix_gap and not issue_count else
                f"{issue_count} conflict(s)/missing item(s) plus unresolved gaps in the capability coverage matrix"
            )
            output.setdefault("consistency_notes", []).append(
                f"[Auto-corrected] Status was reported as \"{stated_status}\" but {reason} "
                f"— that cannot be fully ready, so the status was corrected to \"{minimum_status}\"."
            )
            if minimum_status == "READY WITH WARNINGS":
                output["recommendation"] = "Resolve the flagged conflicts/gaps before treating this package as final."
            else:
                output["recommendation"] = "Significant gaps found — re-run the affected agent(s) before handing this package off."


if __name__ == "__main__":
    import json
    from agents.business_analyst import BusinessAnalystAgent
    from agents.product_manager import ProductManagerAgent
    from agents.product_requirements import ProductRequirementsAgent
    from agents.ux_product_flow import UXProductFlowAgent
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners")]

    BusinessAnalystAgent().run(ctx)
    ProductManagerAgent().run(ctx)
    ProductRequirementsAgent().run(ctx)
    UXProductFlowAgent().run(ctx)
    contribution = AIHandoffValidationAgent().run(ctx)

    print(json.dumps(contribution.model_dump(), indent=2, default=str))
    print("\nFinal status:", contribution.output["final_handoff_status"])

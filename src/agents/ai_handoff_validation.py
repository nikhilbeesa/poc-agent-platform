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
    max_output_tokens = 4000

    def build_prompt(self, context: ProjectContext) -> str:
        contributions_summary = "\n\n".join(
            f"--- {c.agent.value} ---\n{c.output}" for c in context.agent_contributions
        )
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

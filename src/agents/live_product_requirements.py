"""
Chunked LIVE generation for the PRD.

  functional_requirements   one detailed entry per FR (parallel batches).
                            ID, feature name and dependencies come from the BRD
                            in code; the model writes purpose, trigger, inputs,
                            behavior, outputs, validation, error scenarios.
  overview / roles / nav    one call (roles are normalized to the BRD's exact
                            role names afterwards).
  constraints               one call (technical + security/privacy/access).
  per-module notes          one technical + one security note for EVERY module
                            (batched) so no capability lacks either.
  AI feature specs          only for FRs that are actually AI features.
  everything else           derived from the BRD in code: personas, journeys,
                            goals, capabilities, business rules, NFRs, success
                            metrics, and the MVP / Phase 2 / Future split — which
                            is a straight partition of the BRD's P0-P3 priorities,
                            so PRD scope can never contradict the BRD or stories.
"""

from __future__ import annotations

import json
import re

import chunked as ch
from context import AgentRole, ProjectContext

ROLE = AgentRole.PRODUCT_REQUIREMENTS.value

PATCHABLE = [
    "product_overview", "roles_and_permissions", "navigation_pattern", "navigation_behavior",
    "notifications_and_confirmations", "validation_and_error_handling", "state_behaviors",
    "audit_and_versioning", "technical_integration_constraints", "security_privacy_access_constraints",
    "product_goals", "target_users", "assumptions", "dependencies", "release_milestones", "out_of_scope",
]

# Strong AI signals only — a bare "recommended" (as in "MFA recommended") must not turn an
# ordinary requirement into an AI feature spec.
_AI_WORDS = re.compile(r"\b(ai|a\.i\.|ai-powered|ai-driven|machine learning|ml|chatbot|virtual assistant|predictive|generative|recommendation engine|recommendation algorithm|smart matching|automated matching)\b", re.I)

FR_SHAPE = """{
  "functional_requirements": [{
    "fr_id": "FR-001",
    "purpose": "...", "actor": "exact role name", "trigger": "the specific user/system event",
    "preconditions": "...", "inputs": ["..."], "expected_behavior": "what the system does, step by step",
    "outputs": ["..."], "user_visible_result": "...", "validation": "...",
    "error_scenarios": ["..."]
  }]
}"""

OVERVIEW_SHAPE = """{
  "product_overview": "a clear multi-sentence description of the product",
  "roles_and_permissions": [{"role": "exact BRD role name", "permissions": ["specific action", "..."]}],
  "navigation_pattern": "EXACTLY ONE short label naming the single navigation pattern, e.g. 'Left sidebar (desktop) + bottom tab bar (mobile)'",
  "navigation_behavior": "2-4 sentences elaborating that ONE pattern: what is primary vs secondary, and how each role's menu differs",
  "notifications_and_confirmations": ["..."],
  "validation_and_error_handling": "...",
  "state_behaviors": {"loading": "...", "empty": "...", "success": "...", "failure": "...", "processing": "..."},
  "audit_and_versioning": "..."
}"""

CONSTRAINTS_SHAPE = """{
  "technical_integration_constraints": {
    "application_type": "...", "major_system_capabilities": ["..."], "external_integrations": ["..."],
    "data_sources": ["..."], "api_dependencies": ["..."], "real_time_requirements": "...",
    "authentication_dependencies": "...", "platform_deployment_constraints": "..."
  },
  "security_privacy_access_constraints": {
    "authentication_requirements": "...", "mfa_requirements": "...", "roles": ["..."],
    "access_restrictions": ["who cannot see or do what"], "sensitive_data_handling": "...",
    "privacy_requirements": "...", "audit_requirements": "...", "approval_requirements": ["..."],
    "ux_implications": ["concrete statements, e.g. 'Approve action must not be available to unauthorized roles'"]
  }
}"""

NOTES_SHAPE = """{
  "notes": [{"module_id": "MOD-01", "technical": "a technical consideration specific to THIS module", "security": "a security/privacy consideration specific to THIS module"}]
}"""

AI_SHAPE = """{
  "specs": [{
    "fr_id": "FR-001", "feature": "...", "purpose": "...", "input_data": "...", "trigger": "...",
    "processing_behavior": "...", "output": "...", "confidence_handling": "...", "explainability": "...",
    "user_control": "...", "edit_override_behavior": "...", "failure_behavior": "...", "fallback_behavior": "...",
    "privacy_considerations": "...", "data_usage": "...", "security_considerations": "...",
    "performance_expectations": "..."
  }]
}"""


def _fix_roles(model_roles, ba_roles: list[dict]) -> list[dict]:
    """Forces roles_and_permissions onto the BRD's exact role names and makes
    sure every BRD role is present."""
    names = [r["role"] for r in ba_roles]
    by_name: dict[str, list[str]] = {}
    for entry in ch.as_list(model_roles):
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("role", ""))
        low = raw.lower()
        target = next((n for n in names if n == raw), None) or \
                 next((n for n in names if low and (low == n.lower() or low in n.lower() or n.lower() in low)), None)
        if target:
            by_name.setdefault(target, [])
            for p in ch.as_str_list(entry.get("permissions")):
                if p not in by_name[target]:
                    by_name[target].append(p)
    out = []
    for r in ba_roles:
        perms = by_name.get(r["role"]) or [p.strip() for p in re.split(r"[;,]", str(r.get("permissions", ""))) if p.strip()]
        out.append({"role": r["role"], "permissions": perms})
    return out


def generate(context: ProjectContext, client) -> dict:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    if ba is None or pm is None:
        raise RuntimeError("The PRD needs the Business Analyst and Product Manager outputs first.")
    ba_out, pm_out = ba.output, pm.output
    reqs = ba_out.get("requirements", [])
    modules = ba_out.get("modules", [])
    ba_roles = ba_out.get("roles", [])
    role_names = [r["role"] for r in ba_roles]
    story_of = {(s.get("related_fr_ids") or [None])[0]: s for s in pm_out.get("stories", [])}
    frs_by_mod: dict[str, list[dict]] = {}
    for r in reqs:
        frs_by_mod.setdefault(r.get("module_id"), []).append(r)

    previous = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    prev_out = previous.output if previous else {}
    revising = bool(prev_out.get("functional_requirements"))
    notes = ch.notes_for_document(context.resolution_notes or [], ROLE)
    prev_frs = {f["id"]: f for f in prev_out.get("functional_requirements", [])}

    # ------------------------------------------------------------------ FRs
    units = [{"key": r["id"], "fr": r, "story": story_of.get(r["id"], {})} for r in reqs]

    def fr_hash(u):
        s = u["story"]
        return ch.fingerprint([[u["fr"].get(k) for k in ("id", "name", "description", "actor", "priority", "module", "dependencies")],
                               [s.get(k) for k in ("trigger", "preconditions", "main_flow", "exception_flow")], role_names])

    def fr_needles(u):
        return [u["key"]], [u["fr"]["name"]]

    def fr_prompt(batch, notes_by_key, prev_map):
        blocks = []
        for u in batch:
            fr, s = u["fr"], u["story"]
            blocks.append(
                f"- {fr['id']} \"{fr['name']}\" [module: {fr.get('module')}] actor={fr.get('actor')} priority={fr.get('priority')}\n"
                f"  description: {fr.get('description')}\n"
                f"  story trigger: {s.get('trigger', '')} | preconditions: {s.get('preconditions', '')}\n"
                f"  story main flow: {' > '.join(ch.as_str_list(s.get('main_flow')))}\n"
                f"  story exception flow: {s.get('exception_flow', '')}"
            )
        revisions = "".join(
            ch.revision_block(notes_by_key.get(u["key"], []), ch.clean(prev_map[u["key"]]) if u["key"] in prev_map else None)
            for u in batch if notes_by_key.get(u["key"])
        )
        return (
            ch.tag("prd.functional_requirements", [u["key"] for u in batch]) + ch.locked_block(context) +
            "You are a senior product manager writing the Functional Requirements section of a PRD. "
            "Write ONE detailed entry per requirement below, precise enough that a designer and an "
            "engineer could build from it without asking questions.\n\n" + ch.idea_block(context) +
            "\nRoles (use these exact names for `actor`): " + ", ".join(role_names) +
            "\n\nRequirements:\n" + "\n".join(blocks) + "\n\n"
            "Each entry: purpose; actor; the specific trigger; preconditions; concrete inputs; "
            "expected_behavior as the actual sequence of system behavior; outputs; the user-visible "
            "result; validation rules; and 2-4 realistic error scenarios. Never write generic filler "
            "that could describe any requirement. Echo each id in `fr_id`.\n\n"
            + revisions + "Respond ONLY with JSON in exactly this shape:\n" + FR_SHAPE
        )

    fr_items, fr_stats = ch.generate_units(
        label="PRD functional requirements", units=units, prev_by_key=prev_frs, notes=notes, hash_of=fr_hash,
        needles_of=fr_needles, make_prompt=fr_prompt, key_field="fr_id", list_key="functional_requirements",
        client=client, batch_size=6, max_tokens=9000,
    )

    # ------------------------------------------------- per-module notes
    module_units = [{"key": m["id"], "module": m, "frs": frs_by_mod.get(m["id"], [])} for m in modules]
    prev_notes = {n["module_id"]: n for n in prev_out.get("_module_notes", [])}

    def mod_hash(u):
        return ch.fingerprint([u["module"], [f["name"] for f in u["frs"]]])

    def mod_prompt(batch, notes_by_key, prev_map):
        blocks = "\n".join(
            f"- {u['module']['id']} {u['module']['name']}: {u['module'].get('purpose', '')}\n  requirements: "
            + "; ".join(f["name"] for f in u["frs"]) for u in batch
        )
        revisions = "".join(
            ch.revision_block(notes_by_key.get(u["key"], []), ch.clean(prev_map[u["key"]]) if u["key"] in prev_map else None)
            for u in batch if notes_by_key.get(u["key"])
        )
        return (
            ch.tag("prd.module_notes", [u["key"] for u in batch]) + ch.locked_block(context) +
            "You are a senior architect. For EACH module below write one technical note and one "
            "security/privacy note that are specific to that module — not a sentence that could be "
            "swapped between modules.\n\n" + ch.idea_block(context) + "\nModules:\n" + blocks + "\n\n"
            + revisions + "Respond ONLY with JSON in exactly this shape:\n" + NOTES_SHAPE
        )

    mod_items, _ = ch.generate_units(
        label="Per-module technical/security notes", units=module_units, prev_by_key=prev_notes, notes=notes,
        hash_of=mod_hash, needles_of=lambda u: ([u["key"]], [u["module"]["name"]]), make_prompt=mod_prompt,
        key_field="module_id", list_key="notes", client=client, batch_size=6, max_tokens=6000,
    )

    # ------------------------------------------------------ AI feature specs
    ai_frs = [r for r in reqs if _AI_WORDS.search(f"{r.get('name', '')} {r.get('description', '')}")]
    ai_units = [{"key": r["id"], "fr": r} for r in ai_frs]
    prev_ai = {a.get("related_fr"): {**a, "fr_id": a.get("related_fr")} for a in prev_out.get("ai_feature_specifications", [])}

    def ai_prompt(batch, notes_by_key, prev_map):
        blocks = "\n".join(f"- {u['fr']['id']} \"{u['fr']['name']}\": {u['fr'].get('description')}" for u in batch)
        return (
            ch.tag("prd.ai_specs", [u["key"] for u in batch]) +
            "You are a senior product manager specifying AI-powered features. For each requirement "
            "below write a full AI feature specification: what data it uses, when it runs, what it "
            "outputs, how confidence and explainability are handled, what control the user keeps "
            "(accept/edit/dismiss), and what happens on failure. AI output must never take a binding "
            "action without the user.\n\n" + ch.idea_block(context) + "\nFeatures:\n" + blocks +
            "\n\nRespond ONLY with JSON in exactly this shape:\n" + AI_SHAPE
        )

    ai_items, _ = ch.generate_units(
        label="AI feature specifications", units=ai_units, prev_by_key=prev_ai, notes=notes,
        hash_of=lambda u: ch.fingerprint([u["fr"].get("name"), u["fr"].get("description")]),
        needles_of=lambda u: ([u["key"]], [u["fr"]["name"]]), make_prompt=ai_prompt,
        key_field="fr_id", list_key="specs", client=client, batch_size=4, max_tokens=6000,
    ) if ai_units else ({}, {})

    # ------------------------------------------------------------ core sections
    core: dict = {}
    if revising:
        core = {k: prev_out[k] for k in PATCHABLE if k in prev_out}
    else:
        fr_lines = "\n".join(
            f"- {m['id']} {m['name']}: " + "; ".join(f"{f['id']} {f['name']}" for f in frs_by_mod.get(m["id"], []))
            for m in modules
        )
        role_lines = "\n".join(
            f"- {r['role']}: purpose={r.get('purpose', '')} | capabilities={r.get('capabilities', '')} | "
            f"permissions={r.get('permissions', '')} | restricted={r.get('restricted', '')}" for r in ba_roles
        )
        overview_prompt = (
            ch.tag("prd.overview") + ch.locked_block(context) +
            "You are a senior product manager writing the framing sections of a PRD.\n\n" + ch.idea_block(context) +
            "\nBRD roles (roles_and_permissions MUST use exactly these names and MUST reflect each role's "
            "stated scope and restrictions — translate, do not redefine):\n" + role_lines +
            "\n\nModules and requirements:\n" + fr_lines +
            "\n\nRules:\n- navigation_pattern is ONE single named pattern; navigation_behavior elaborates that "
            "same pattern and states how the menu differs by role (e.g. which roles see admin items).\n"
            "- roles_and_permissions: only actions the requirements above actually support, and every action "
            "a requirement grants a role must appear for that role.\n- notifications_and_confirmations: 10+ "
            "specific items tied to real events.\n\nRespond ONLY with JSON in exactly this shape:\n" + OVERVIEW_SHAPE
        )
        constraints_prompt = (
            ch.tag("prd.constraints") + ch.locked_block(context) +
            "You are a senior architect writing the technical and security constraints of a PRD.\n\n" +
            ch.idea_block(context) + "\nModules: " + ", ".join(m["name"] for m in modules) +
            "\nBRD integrations: " + json.dumps(ba_out.get("integrations", []), default=str) +
            "\nBRD security requirements: " + json.dumps(ba_out.get("security_requirements", []), default=str) +
            "\nBRD payment requirements: " + json.dumps(ba_out.get("payment_requirements"), default=str) +
            "\nRoles: " + ", ".join(role_names) +
            "\n\nState explicitly that applicable regulation must be confirmed for the launch geography if "
            "unknown — never invent a compliance claim. access_restrictions must state concretely who cannot "
            "see or do what.\n\nRespond ONLY with JSON in exactly this shape:\n" + CONSTRAINTS_SHAPE
        )
        ch.report("Writing PRD overview, roles, navigation and constraints…")
        ov, cons = ch.run_parallel("PRD core sections", [
            lambda: ch.call_json(client, overview_prompt, max_tokens=7000),
            lambda: ch.call_json(client, constraints_prompt, max_tokens=6000),
        ], workers=2)
        core = {**ov, **cons}

    # --------------------------------------------------------------- assemble
    functional_requirements = []
    for r in reqs:
        raw = fr_items[r["id"]]
        functional_requirements.append({
            "id": r["id"], "feature": r["name"], "purpose": raw.get("purpose", ""),
            "actor": raw.get("actor") or r.get("actor", ""), "trigger": raw.get("trigger", ""),
            "preconditions": raw.get("preconditions", ""), "inputs": ch.as_str_list(raw.get("inputs")),
            "expected_behavior": raw.get("expected_behavior", ""), "outputs": ch.as_str_list(raw.get("outputs")),
            "user_visible_result": raw.get("user_visible_result", ""), "validation": raw.get("validation", ""),
            "error_scenarios": ch.as_str_list(raw.get("error_scenarios")),
            "dependencies": list(r.get("dependencies", [])), "_src": raw.get("_src"),
        })

    mod_note_rows = [{"module_id": m["id"], **{k: mod_items[m["id"]].get(k, "") for k in ("technical", "security")},
                      "_src": mod_items[m["id"]].get("_src")} for m in modules if m["id"] in mod_items]
    tech_notes = [{"capability": m["name"], "note": n["technical"]} for m, n in zip(modules, mod_note_rows) if n["technical"]]
    sec_notes = [{"capability": m["name"], "note": n["security"]} for m, n in zip(modules, mod_note_rows) if n["security"]]

    tech = dict(core.get("technical_integration_constraints") or {})
    tech["capability_technical_notes"] = tech_notes
    sec = dict(core.get("security_privacy_access_constraints") or {})
    sec["capability_security_notes"] = sec_notes
    sec.setdefault("roles", role_names)

    tiers = {"P0": [], "P1": [], "P2": [], "P3": []}
    for r in reqs:
        tiers.setdefault(r.get("priority", "P1"), []).append(f"{r['id']} — {r['name']}")
    mvp = tiers["P0"] + tiers["P1"]
    phase_2 = tiers["P2"]
    future = tiers["P3"] + [str(x) for x in ba_out.get("future_enhancements", [])]

    ai_specs = []
    for r in ai_frs:
        raw = ai_items.get(r["id"])
        if raw:
            spec = {k: v for k, v in raw.items() if k not in ("fr_id",)}
            spec["related_fr"] = r["id"]
            spec.setdefault("feature", r["name"])
            ai_specs.append(spec)

    exec_sum = ba_out.get("executive_summary") or {}
    personas = [{"name": p.get("name", ""), "role": p.get("role", ""), "goals": p.get("goals", "")}
                for p in ba_out.get("user_personas", [])]
    out = {
        "summary": f"PRD covering {len(modules)} capabilities and {len(functional_requirements)} detailed functional "
                   f"requirements ({len(mvp)} MVP, {len(phase_2)} Phase 2, {len(future)} future).",
        "product_overview": core.get("product_overview", ""),
        "product_goals": core.get("product_goals") or [str(o) for o in ba_out.get("business_objectives", [])],
        "target_users": core.get("target_users") or (exec_sum.get("target_users", "") if isinstance(exec_sum, dict) else ""),
        "personas": personas,
        "user_journeys": [f"{k}: {v}" for k, v in (ba_out.get("user_journeys") or {}).items()],
        "product_capabilities": [f"{m['id']}: {m['name']}" for m in modules],
        "functional_requirements": functional_requirements,
        "roles_and_permissions": _fix_roles(core.get("roles_and_permissions"), ba_roles),
        "product_business_rules": [f"{b['id']}: {b['rule']}" for b in ba_out.get("business_rules", [])],
        "navigation_pattern": core.get("navigation_pattern", ""),
        "navigation_behavior": core.get("navigation_behavior", ""),
        "notifications_and_confirmations": ch.as_str_list(core.get("notifications_and_confirmations")),
        "validation_and_error_handling": core.get("validation_and_error_handling", ""),
        "state_behaviors": core.get("state_behaviors") or {},
        "audit_and_versioning": core.get("audit_and_versioning", ""),
        "non_functional_requirements": [f"{n['id']}: {n.get('requirement', '')}" for n in ba_out.get("nfrs", [])],
        "technical_integration_constraints": tech,
        "security_privacy_access_constraints": sec,
        "ai_feature_specifications": ai_specs,
        "mvp_scope": mvp, "phase_2_scope": phase_2, "future_scope": future,
        "success_metrics": [str(k.get("kpi", "")) for k in ba_out.get("kpis", []) if isinstance(k, dict)],
        "out_of_scope": core.get("out_of_scope") or [str(x) for x in ba_out.get("scope_out", [])],
        "dependencies": core.get("dependencies") or [str(x) for x in ba_out.get("dependencies", [])],
        "assumptions": core.get("assumptions") or [str(x) for x in ba_out.get("assumptions", [])],
        "release_milestones": core.get("release_milestones") or [
            {"milestone": p.get("phase", ""), "description": p.get("description", "")}
            for p in ba_out.get("release_strategy", []) if isinstance(p, dict)],
        "_module_notes": mod_note_rows,
    }

    if revising and notes:
        current = {k: out[k] for k in PATCHABLE if k in out}
        prompt = (
            ch.tag("prd.revise_core") + ch.locked_block(context) +
            "You are a senior product manager revising a PRD after a validation review.\n\nFindings:\n"
            + "\n".join(f"- {n}" for n in notes) + "\n\nCurrent sections you may edit:\n"
            + json.dumps(current, indent=1, default=str) +
            "\n\nReturn ONLY the sections that must change, each as a COMPLETE replacement in the same JSON "
            "type it has now. roles_and_permissions must keep the BRD's exact role names. Change nothing the "
            "findings do not require. If none of the findings concern these sections return {\"changes\": {}}.\n"
            "Respond ONLY with JSON: {\"changes\": {\"<section>\": <new value>}}"
        )
        data = ch.call_json(client, prompt, max_tokens=7000)
        ch.apply_section_patch(out, data.get("changes"), PATCHABLE)
        out["roles_and_permissions"] = _fix_roles(out.get("roles_and_permissions"), ba_roles)

    ch.report(f"PRD: {len(functional_requirements)} functional requirements "
              f"({fr_stats['generated']} generated, {fr_stats['reused']} reused).")
    return out

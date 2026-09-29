"""
Chunked LIVE generation for the UX / Product Flow specification.

  1. plan     one call  -> which screens each module needs (1-3 per module) and
                           which FRs each screen carries. Repaired in code so
                           every FR is on at least one screen and every module
                           has a screen.
  2. screens  batches   -> per-screen detail, INCLUDING that screen's states,
                           interactions and forms (so depth scales with screens)
  3. flows    batches   -> one user flow per user story (FLOW-0NN for US-0NN)
  4. core     one call  -> navigation structure (per role), notifications,
                           responsive, accessibility

Enforced in code, never left to the model: screen/flow IDs; the navigation label
(the PRD's, verbatim, on every screen); the roles/permissions matrix (a copy of
the PRD's); entry/exit points that reference screens that don't exist; and
business-rule traceability (every BRD business rule appears on a screen of its
module). Revision passes reuse every screen/flow whose inputs are unchanged and
no note names.
"""

from __future__ import annotations

import json

import chunked as ch
from context import AgentRole, ProjectContext

ROLE = AgentRole.UX_PRODUCT_FLOW.value

PATCHABLE = ["navigation", "notifications_and_feedback", "responsive_requirements", "accessibility"]
GENERIC_ENTRIES = ["Main Navigation", "Landing Page", "Notification", "Email link", "Sign-in"]
PHASE_OF = {"P0": "MVP", "P1": "MVP", "P2": "Phase 2", "P3": "Future"}

PLAN_SHAPE = """{
  "screens": [{"module_id": "MOD-01", "name": "...", "purpose": "...", "primary_role": "exact role name", "fr_ids": ["FR-001"]}]
}"""

SCREEN_SHAPE = """{
  "screens": [{
    "screen_id": "SCR-001",
    "entry_points": ["screen name or generic entry"], "exit_points": ["screen name"],
    "primary_actions": ["..."], "secondary_actions": ["..."],
    "information_displayed": ["..."], "data_required": ["..."], "ui_elements_required": ["..."],
    "permissions": "what each role may do on this screen",
    "business_rules": ["BR-001: rule enforced on this screen"], "dependencies": ["..."],
    "states": [{"state": "loading|empty|success|failure", "what_user_sees": "...", "available_actions": ["..."], "disabled_actions": ["..."], "next_step": "..."}],
    "interactions": [{"action": "...", "preconditions": "...", "system_behavior": "...", "user_visible_result": "...", "next_state": "...", "possible_errors": ["..."]}],
    "forms": [{"form_name": "...", "fields": [{"field": "...", "purpose": "...", "data_type": "...", "required": true, "validation": "...", "default_value": "..."}]}]
  }]
}"""

FLOW_SHAPE = """{
  "flows": [{
    "fr_id": "FR-001", "name": "...", "actor": "exact role name", "goal": "...", "starting_point": "...",
    "preconditions": "...", "main_path": ["step", "..."], "alternative_paths": ["..."], "error_paths": ["..."],
    "decision_points": ["..."], "completion_state": "..."
  }]
}"""

CORE_SHAPE = """{
  "navigation": {"structure": "how the ONE pattern's items are organized AND how the menu differs per role", "mobile_behavior": "how that same pattern adapts on mobile"},
  "notifications_and_feedback": {"success": "...", "error": "...", "loading": "...", "empty": "..."},
  "responsive_requirements": {"desktop": "...", "tablet": "...", "mobile": "..."},
  "accessibility": ["..."]
}"""


def _norm(text: str) -> str:
    return "".join(c for c in str(text).lower() if c.isalnum())


def _norm_role(role: str, fallback: str, role_names: list[str]) -> str:
    if not role_names:
        return role or fallback
    for cand in (role, fallback):
        if cand in role_names:
            return cand
    for cand in (role, fallback):
        low = (cand or "").lower()
        for n in role_names:
            if low and (low == n.lower() or low in n.lower() or n.lower() in low):
                return n
    return role_names[0]


def _phase(fr: dict) -> str:
    return PHASE_OF.get(fr.get("priority"), "MVP")


def generate(context: ProjectContext, client) -> dict:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    if not (ba and pm and prd):
        raise RuntimeError("The UX spec needs the BA, PM and PRD outputs first.")
    ba_out, pm_out, prd_out = ba.output, pm.output, prd.output
    reqs = ba_out.get("requirements", [])
    modules = ba_out.get("modules", [])
    role_names = [r["role"] for r in ba_out.get("roles", []) if r.get("role")]
    nav_pattern = prd_out.get("navigation_pattern", "")
    fr_by_id = {r["id"]: r for r in reqs}
    story_of = {(s.get("related_fr_ids") or [None])[0]: s for s in pm_out.get("stories", [])}
    us_of = {rid: s["id"] for rid, s in story_of.items() if rid}
    frs_by_mod: dict[str, list[dict]] = {}
    for r in reqs:
        frs_by_mod.setdefault(r.get("module_id"), []).append(r)
    brs_by_mod: dict[str, list[dict]] = {}
    for b in ba_out.get("business_rules", []):
        brs_by_mod.setdefault(b.get("module_id"), []).append(b)
    mod_name = {m["id"]: m["name"] for m in modules}

    previous = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)
    prev_out = previous.output if previous else {}
    revising = bool(prev_out.get("screens"))
    notes = ch.notes_for_document(context.resolution_notes or [], ROLE)

    # ---------------------------------------------------------------- 1. plan
    plan: list[dict] = []  # entries: {id?, module_id, name, purpose, primary_role, fr_ids}
    if revising:
        for s in prev_out.get("screens", []):
            plan.append({"id": s["id"], "module_id": s.get("module_id"), "name": s["name"], "purpose": s.get("purpose", ""),
                         "primary_role": s.get("primary_role", ""), "fr_ids": list(s.get("related_requirement_ids", []))})
        valid_mods = {m["id"] for m in modules}
        plan = [p for p in plan if p["module_id"] in valid_mods]
        for p in plan:
            p["fr_ids"] = [f for f in p["fr_ids"] if f in fr_by_id]
        need_modules = [m for m in modules if not any(p["module_id"] == m["id"] for p in plan)]
    else:
        need_modules = list(modules)

    if need_modules:
        ch.report("Planning screens…")
        mod_lines = "\n".join(
            f"- {m['id']} {m['name']}: {m.get('purpose', '')}\n  requirements: " +
            "; ".join(f"{f['id']} {f['name']} [{_phase(f)}]" for f in frs_by_mod.get(m["id"], []))
            for m in need_modules
        )
        prompt = (
            ch.tag("ux.plan", [m["id"] for m in need_modules]) + ch.locked_block(context) +
            "You are a senior UX designer planning the screen inventory of a product from its "
            "requirements.\n\n" + ch.idea_block(context) +
            "\nRoles (use these exact names for primary_role): " + ", ".join(role_names) +
            "\nNavigation pattern: " + nav_pattern +
            "\n\nModules and their requirements:\n" + mod_lines + "\n\n"
            "Plan 1 to 3 screens per module (2-3 for a module with 5+ requirements — split by real "
            "user tasks, e.g. a list/browse screen and a detail/manage screen). EVERY requirement id "
            "must be carried by at least one screen. Name each screen after what it is, using the "
            "module's exact name for its primary screen (e.g. \"<Module name>\" and \"<Module name> — "
            "Detail\"); screen names must be unique. Screens for a module whose requirements are all "
            "Phase 2/Future are still planned.\n\nRespond ONLY with JSON in exactly this shape:\n" + PLAN_SHAPE
        )
        data = ch.call_json(client, prompt, max_tokens=8000)
        for s in ch.as_list(data.get("screens")):
            if not isinstance(s, dict) or s.get("module_id") not in {m["id"] for m in need_modules} or not s.get("name"):
                continue
            plan.append({"id": None, "module_id": s["module_id"], "name": str(s["name"]).strip(), "purpose": str(s.get("purpose", "")),
                         "primary_role": s.get("primary_role", ""), "fr_ids": [f for f in ch.as_list(s.get("fr_ids")) if f in fr_by_id]})

    # repair: unique names, every FR on a screen, every module has a screen
    seen_names: set[str] = set()
    for p in plan:
        base = p["name"]
        if _norm(p["name"]) in seen_names:
            p["name"] = f"{base} ({mod_name.get(p['module_id'], p['module_id'])})"
        seen_names.add(_norm(p["name"]))
    for m in modules:
        mine = [p for p in plan if p["module_id"] == m["id"]]
        if not mine:
            frs = frs_by_mod.get(m["id"], [])
            plan.append({"id": None, "module_id": m["id"], "name": m["name"], "purpose": m.get("purpose", ""),
                         "primary_role": frs[0].get("actor", "") if frs else "", "fr_ids": [f["id"] for f in frs]})
            mine = [plan[-1]]
        covered = {f for p in mine for f in p["fr_ids"]}
        for f in frs_by_mod.get(m["id"], []):
            if f["id"] not in covered:
                mine[0]["fr_ids"].append(f["id"])
    next_num = max([ch.id_num(p["id"]) or 0 for p in plan if p["id"]] + [0]) + 1
    for p in plan:
        if not p["id"]:
            p["id"] = ch.make_id("SCR", next_num)
            next_num += 1
        p["primary_role"] = _norm_role(p["primary_role"], "", role_names)
    plan.sort(key=lambda p: ch.id_num(p["id"]) or 0)
    module_order = {m["id"]: i for i, m in enumerate(modules)}
    screen_names = [p["name"] for p in plan]

    # ------------------------------------------------------------- 2. screens
    prev_chunks: dict[str, dict] = {}
    if revising:
        for s in prev_out.get("screens", []):
            sid = s["id"]
            prev_chunks[sid] = {
                **{k: v for k, v in s.items()},
                "states": [x for x in prev_out.get("screen_states", []) if x.get("screen_id") == sid],
                "interactions": [x for x in prev_out.get("interactions", []) if x.get("screen_id") == sid],
                "forms": [x for x in prev_out.get("forms", []) if x.get("screen_id") == sid],
                "screen_id": sid,
            }

    screen_units = [{"key": p["id"], "plan": p} for p in plan]
    perms_lines = "\n".join(f"- {r['role']}: {', '.join(r.get('permissions', []))}" for r in prd_out.get("roles_and_permissions", []))

    def screen_hash(u):
        p = u["plan"]
        return ch.fingerprint([p["name"], p["purpose"], p["primary_role"], p["module_id"],
                               [(f, fr_by_id[f]["name"], fr_by_id[f].get("priority")) for f in p["fr_ids"]],
                               [(b["id"], b["rule"]) for b in brs_by_mod.get(p["module_id"], [])], nav_pattern])

    def screen_needles(u):
        p = u["plan"]
        return [p["id"]] + p["fr_ids"], [p["name"]]

    def screen_prompt(batch, notes_by_key, prev_map):
        blocks = []
        for u in batch:
            p = u["plan"]
            fr_lines = []
            for fid in p["fr_ids"]:
                fr = fr_by_id[fid]
                s = story_of.get(fid, {})
                fr_lines.append(f"    {fid} {fr['name']} ({fr.get('priority')}, {_phase(fr)}): {fr.get('description')} "
                                f"| story flow: {' > '.join(ch.as_str_list(s.get('main_flow')))}")
            brs = "; ".join(f"{b['id']}: {b['rule']}" for b in brs_by_mod.get(p["module_id"], [])) or "(none)"
            blocks.append(f"- {p['id']} \"{p['name']}\" [module {p['module_id']}] primary role: {p['primary_role']}\n"
                          f"  purpose: {p['purpose']}\n  requirements on this screen:\n" + "\n".join(fr_lines) +
                          f"\n  business rules of this module: {brs}")
        revisions = "".join(
            ch.revision_block(notes_by_key.get(u["key"], []), ch.clean(prev_map[u["key"]]) if u["key"] in prev_map else None)
            for u in batch if notes_by_key.get(u["key"])
        )
        return (
            ch.tag("ux.screens", [u["key"] for u in batch]) + ch.locked_block(context) +
            "You are a senior UX designer specifying screens for an independent Design AI Agent that "
            "will build the UI from this text alone. Specify each screen below completely.\n\n" + ch.idea_block(context) +
            "\nRoles and permissions:\n" + perms_lines +
            "\n\nAll screens (entry_points/exit_points MUST be names from this list, or one of: " +
            ", ".join(GENERIC_ENTRIES) + "):\n" + "\n".join(f"- {n}" for n in screen_names) +
            "\n\nScreens to specify:\n" + "\n".join(blocks) + "\n\n"
            "For each screen: real primary/secondary actions taken from its requirements; the information "
            "displayed and data required; the concrete UI elements; per-role permissions; the business "
            "rules enforced ON this screen (by ID) with the interface behavior that enforces them; "
            "FOUR states (loading, empty, success, failure) each saying what the user sees, available and "
            "disabled actions and the next step; one interaction for each primary action (preconditions, "
            "system behavior, visible result, next state, possible errors); and every form the screen "
            "contains with real fields, types, required flags and validation. For any restriction on a "
            "role (e.g. an admin with limited access to sensitive data), state the interface safeguard "
            "(masked field, confirmation modal, re-authentication, access-logged notice). Echo each id "
            "in `screen_id`.\n\n" + revisions + "Respond ONLY with JSON in exactly this shape:\n" + SCREEN_SHAPE
        )

    screen_items, screen_stats = ch.generate_units(
        label="UX screens", units=screen_units, prev_by_key=prev_chunks, notes=notes, hash_of=screen_hash,
        needles_of=screen_needles, make_prompt=screen_prompt, key_field="screen_id", list_key="screens",
        client=client, batch_size=3, max_tokens=10000,
    )

    # -------------------------------------------------------------- 3. flows
    screens_of_fr: dict[str, list[dict]] = {}
    for p in plan:
        for f in p["fr_ids"]:
            screens_of_fr.setdefault(f, []).append(p)
    prev_flows = {}
    for f in prev_out.get("user_flows", []):
        ids = f.get("related_requirement_ids") or []
        if ids:
            prev_flows[ids[0]] = f
    flow_units = [{"key": r["id"], "fr": r, "story": story_of.get(r["id"], {}), "screens": screens_of_fr.get(r["id"], [])} for r in reqs]

    def flow_hash(u):
        s = u["story"]
        return ch.fingerprint([u["fr"].get("name"), u["fr"].get("description"), u["fr"].get("actor"),
                               [s.get(k) for k in ("main_flow", "alternative_flow", "exception_flow", "trigger")],
                               [(p["id"], p["name"]) for p in u["screens"]], role_names])

    def flow_prompt(batch, notes_by_key, prev_map):
        blocks = []
        for u in batch:
            fr, s = u["fr"], u["story"]
            screens = ", ".join(f"{p['id']} \"{p['name']}\"" for p in u["screens"])
            blocks.append(f"- {fr['id']} \"{fr['name']}\" actor={fr.get('actor')}: {fr.get('description')}\n"
                          f"  story main flow: {' > '.join(ch.as_str_list(s.get('main_flow')))}\n"
                          f"  alternative: {s.get('alternative_flow', '')} | exception: {s.get('exception_flow', '')}\n"
                          f"  screens involved: {screens}")
        revisions = "".join(
            ch.revision_block(notes_by_key.get(u["key"], []), ch.clean(prev_map[u["key"]]) if u["key"] in prev_map else None)
            for u in batch if notes_by_key.get(u["key"])
        )
        return (
            ch.tag("ux.flows", [u["key"] for u in batch]) + ch.locked_block(context) +
            "You are a senior UX designer writing user flows. Write ONE flow per requirement below, "
            "each a real end-to-end path through the screens listed (name the screen at each step), "
            "with the decision points, alternative paths and error paths a designer must cover.\n\n"
            + ch.idea_block(context) + "\nRoles (exact names): " + ", ".join(role_names) +
            "\n\nRequirements:\n" + "\n".join(blocks) + "\n\nEcho each id in `fr_id`.\n\n"
            + revisions + "Respond ONLY with JSON in exactly this shape:\n" + FLOW_SHAPE
        )

    flow_items, flow_stats = ch.generate_units(
        label="UX flows", units=flow_units, prev_by_key=prev_flows, notes=notes, hash_of=flow_hash,
        needles_of=lambda u: ([u["key"], us_of.get(u["key"], "")], [u["fr"]["name"]]), make_prompt=flow_prompt,
        key_field="fr_id", list_key="flows", client=client, batch_size=6, max_tokens=9000,
    )

    # ------------------------------------------------------------ assemble
    screens, states, interactions, forms = [], [], [], []
    valid_targets = {_norm(n) for n in screen_names} | {_norm(g) for g in GENERIC_ENTRIES}

    def clean_points(points, own_name):
        kept = [str(x) for x in ch.as_list(points) if _norm(x) in valid_targets and _norm(x) != _norm(own_name)]
        return kept or ["Main Navigation"]

    for p in plan:
        raw = screen_items[p["id"]]
        frs = [fr_by_id[f] for f in p["fr_ids"]]
        screens.append({
            "id": p["id"], "name": p["name"], "purpose": p["purpose"], "primary_role": p["primary_role"],
            "module_id": p["module_id"],
            "phase": "MVP" if any(_phase(f) == "MVP" for f in frs) else (_phase(frs[0]) if frs else "MVP"),
            "entry_points": clean_points(raw.get("entry_points"), p["name"]),
            "exit_points": clean_points(raw.get("exit_points"), p["name"]),
            "related_story_ids": [us_of[f] for f in p["fr_ids"] if f in us_of],
            "related_requirement_ids": list(p["fr_ids"]),
            "primary_actions": ch.as_str_list(raw.get("primary_actions")),
            "secondary_actions": ch.as_str_list(raw.get("secondary_actions")),
            "navigation": nav_pattern,
            "information_displayed": ch.as_str_list(raw.get("information_displayed")),
            "data_required": ch.as_str_list(raw.get("data_required")),
            "ui_elements_required": ch.as_str_list(raw.get("ui_elements_required")),
            "permissions": raw.get("permissions", ""),
            "business_rules": ch.as_str_list(raw.get("business_rules")),
            "dependencies": ch.as_str_list(raw.get("dependencies")),
            "_src": raw.get("_src"),
        })
        for st in ch.as_list(raw.get("states")):
            if isinstance(st, dict):
                states.append({"screen_id": p["id"], "state": st.get("state", ""), "what_user_sees": st.get("what_user_sees", ""),
                               "available_actions": ch.as_str_list(st.get("available_actions")),
                               "disabled_actions": ch.as_str_list(st.get("disabled_actions")), "next_step": st.get("next_step", "")})
        for it in ch.as_list(raw.get("interactions")):
            if isinstance(it, dict):
                interactions.append({"screen_id": p["id"], "action": it.get("action", ""), "preconditions": it.get("preconditions", ""),
                                     "system_behavior": it.get("system_behavior", ""), "user_visible_result": it.get("user_visible_result", ""),
                                     "next_state": it.get("next_state", ""), "possible_errors": ch.as_str_list(it.get("possible_errors"))})
        for fm in ch.as_list(raw.get("forms")):
            if isinstance(fm, dict) and fm.get("fields"):
                forms.append({"form_name": fm.get("form_name", ""), "screen_id": p["id"], "fields": fm.get("fields")})

    # business-rule traceability backstop: every module BR lands on a screen of its module
    for m in modules:
        mine = [s for s in screens if s["module_id"] == m["id"]]
        for b in brs_by_mod.get(m["id"], []):
            if not any(b["id"] in " ".join(s["business_rules"]) for s in mine):
                mine[0]["business_rules"].append(f"{b['id']}: {b['rule']}")

    flows = []
    for r in reqs:
        raw = flow_items[r["id"]]
        n = ch.id_num(r["id"]) or 0
        flows.append({
            "id": ch.make_id("FLOW", n), "name": raw.get("name", r["name"]),
            "actor": _norm_role(raw.get("actor", ""), r.get("actor", ""), role_names),
            "goal": raw.get("goal", ""), "starting_point": raw.get("starting_point", ""),
            "preconditions": raw.get("preconditions", ""), "main_path": ch.as_str_list(raw.get("main_path")),
            "alternative_paths": ch.as_str_list(raw.get("alternative_paths")), "error_paths": ch.as_str_list(raw.get("error_paths")),
            "decision_points": ch.as_str_list(raw.get("decision_points")), "completion_state": raw.get("completion_state", ""),
            "related_screen_ids": [p["id"] for p in screens_of_fr.get(r["id"], [])],
            "related_requirement_ids": [r["id"]], "related_story_ids": [us_of[r["id"]]] if r["id"] in us_of else [],
            "_src": raw.get("_src"),
        })

    # -------------------------------------------------------------- 4. core
    mvp_screens = [s for s in screens if s["phase"] == "MVP"]
    later_screens = [s for s in screens if s["phase"] != "MVP"]
    if revising:
        core = {k: prev_out[k] for k in PATCHABLE if k in prev_out}
    else:
        ch.report("Writing navigation, notifications and responsive rules…")
        prompt = (
            ch.tag("ux.core") + ch.locked_block(context) +
            "You are a senior UX designer writing the global rules of a UX specification.\n\n" + ch.idea_block(context) +
            "\nNavigation pattern (fixed — do not change or add a second pattern): " + nav_pattern +
            "\nPRD navigation behavior: " + prd_out.get("navigation_behavior", "") +
            "\n\nRoles and permissions:\n" + perms_lines +
            "\n\nMVP screens (eligible for primary navigation):\n" + "\n".join(f"- {s['name']} (role: {s['primary_role']})" for s in mvp_screens) +
            "\n\nPhase 2 / future screens (must NOT be primary navigation items; mention only as a labeled "
            "'Phase 2 (not in MVP)' note):\n" + ("\n".join(f"- {s['name']}" for s in later_screens) or "- none") +
            "\n\nnavigation.structure MUST state, per role, which items that role sees (e.g. \"Admin sees X, "
            "Y in addition\") and where secondary items live; mobile_behavior adapts that SAME pattern. "
            "notifications_and_feedback must be concrete (what the toast/banner/modal says and when), "
            "never one-word placeholders. accessibility 6+ items (WCAG 2.2 AA).\n\n"
            "Respond ONLY with JSON in exactly this shape:\n" + CORE_SHAPE
        )
        core = ch.call_json(client, prompt, max_tokens=6000)

    out = {
        "summary": f"UX specification covering {len(screens)} screens, {len(flows)} user flows, {len(states)} screen states, "
                   f"{len(interactions)} interactions and {len(forms)} forms derived from {len(pm_out.get('stories', []))} "
                   f"user stories across {len(modules)} modules.",
        "information_architecture": [f"{m['name']} ({m['id']}, {'MVP' if any(_phase(f) == 'MVP' for f in frs_by_mod.get(m['id'], [])) else 'Phase 2 / future'}): {m.get('purpose', '')}"
                                     for m in modules],
        "screens": screens, "user_flows": flows, "screen_states": states, "interactions": interactions, "forms": forms,
        "navigation": {"pattern": nav_pattern, **{k: v for k, v in (core.get("navigation") or {}).items() if k != "pattern"}},
        "notifications_and_feedback": core.get("notifications_and_feedback") or {},
        "roles_permissions_matrix": [{"role": r["role"], "permissions": list(r.get("permissions", []))}
                                     for r in prd_out.get("roles_and_permissions", [])],
        "responsive_requirements": core.get("responsive_requirements") or {},
        "accessibility": ch.as_str_list(core.get("accessibility")),
    }

    if revising and notes:
        current = {k: out[k] for k in PATCHABLE if k in out}
        prompt = (
            ch.tag("ux.revise_core") + ch.locked_block(context) +
            "You are a senior UX designer revising the global rules of a UX specification after a "
            "validation review.\n\nFindings:\n" + "\n".join(f"- {n}" for n in notes) +
            "\n\nCurrent sections you may edit:\n" + json.dumps(current, indent=1, default=str) +
            "\n\nReturn ONLY the sections that must change, each as a COMPLETE replacement in the same JSON "
            "type. navigation.pattern must stay exactly '" + nav_pattern + "'; navigation.structure must state "
            "per role which items each role sees. If none of the findings concern these sections return "
            "{\"changes\": {}}.\nRespond ONLY with JSON: {\"changes\": {\"<section>\": <new value>}}"
        )
        data = ch.call_json(client, prompt, max_tokens=5000)
        ch.apply_section_patch(out, data.get("changes"), PATCHABLE)
        out["navigation"]["pattern"] = nav_pattern

    ch.report(f"UX: {len(screens)} screens, {len(flows)} flows ({screen_stats['generated']} screens / "
              f"{flow_stats['generated']} flows generated, {screen_stats['reused']} / {flow_stats['reused']} reused).")
    return out

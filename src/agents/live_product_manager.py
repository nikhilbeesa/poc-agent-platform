"""
Chunked LIVE generation for the Product Manager (user stories).

One story per functional requirement, generated in parallel batches. The
model writes only the story CONTENT (role, story sentence, flows, acceptance
criteria). Everything structural is derived in code so it cannot drift:

  - story ID      US-0NN for FR-0NN (one numbering across BRD/stories/UX)
  - epic          one per BRD module, named exactly after the module
  - feature       the FR's exact name
  - dependencies  the stories of the FRs the FR depends on
  - priority      mapped from the FR's P0-P3 (P0/P1 High, P2 Medium, P3 Low)
  - related FRs   always exactly the FR the story converts

On a revision pass a story is reused unless its FR changed or a note names it.
"""

from __future__ import annotations

import json

import chunked as ch
from context import AgentRole, ProjectContext

ROLE = AgentRole.PRODUCT_MANAGER.value

STORY_SHAPE = """{
  "stories": [{
    "fr_id": "FR-001",
    "role": "exact role name",
    "story": "As a <role>, I want <specific capability>, so that <concrete benefit>",
    "business_value": "why this matters to the business",
    "preconditions": "...", "trigger": "...",
    "main_flow": ["step 1", "step 2", "step 3", "step 4"],
    "alternative_flow": "...", "exception_flow": "...",
    "acceptance_criteria": ["Given ..., when ..., then ...", "..."]
  }]
}"""

PRIORITY_MAP = {"P0": "High", "P1": "High", "P2": "Medium", "P3": "Low"}


def _norm_role(role: str, fr_actor: str, role_names: list[str]) -> str:
    if not role_names:
        return role or fr_actor
    for candidate in (role, fr_actor):
        if candidate in role_names:
            return candidate
    for candidate in (role, fr_actor):
        low = (candidate or "").lower()
        for name in role_names:
            if low and (low == name.lower() or low in name.lower() or name.lower() in low):
                return name
    return role_names[0]


def generate(context: ProjectContext, client) -> dict:
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    if ba is None:
        raise RuntimeError("Product Manager needs the Business Analyst output first.")
    ba_out = ba.output
    reqs = ba_out.get("requirements", [])
    modules = ba_out.get("modules", [])
    role_names = [r.get("role") for r in ba_out.get("roles", []) if r.get("role")]
    mod_by_id = {m["id"]: m for m in modules}
    epic_of = {m["id"]: ch.make_id("EPIC", i) for i, m in enumerate(modules, 1)}
    brs_by_mod: dict[str, list[dict]] = {}
    for b in ba_out.get("business_rules", []):
        brs_by_mod.setdefault(b.get("module_id"), []).append(b)
    us_of = {r["id"]: ch.make_id("US", ch.id_num(r["id"]) or 0) for r in reqs}

    previous = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    prev_by_key = {}
    if previous:
        for s in previous.output.get("stories", []):
            ids = s.get("related_fr_ids") or []
            if ids:
                prev_by_key[ids[0]] = s
    notes = ch.notes_for_document(context.resolution_notes or [], ROLE)

    units = [{"key": r["id"], "fr": r, "brs": brs_by_mod.get(r.get("module_id"), [])} for r in reqs]

    def hash_of(u):
        fr = u["fr"]
        return ch.fingerprint([fr.get(k) for k in ("id", "name", "description", "actor", "priority", "module", "rationale")]
                              + [[(b["id"], b["rule"]) for b in u["brs"]], role_names])

    def needles_of(u):
        return [u["key"], us_of[u["key"]]], [u["fr"]["name"]]

    def make_prompt(batch, notes_by_key, prev_map):
        blocks = []
        for u in batch:
            fr = u["fr"]
            brs = "\n".join(f"    {b['id']}: {b['rule']}" for b in u["brs"]) or "    (none)"
            blocks.append(
                f"- {fr['id']} \"{fr['name']}\" [module: {fr.get('module')}] actor={fr.get('actor')} priority={fr.get('priority')}\n"
                f"  description: {fr.get('description')}\n  rationale: {fr.get('rationale')}\n"
                f"  business rules of this module:\n{brs}"
            )
        revisions = "".join(
            ch.revision_block(notes_by_key.get(u["key"], []), ch.clean(prev_map[u["key"]]) if u["key"] in prev_map else None)
            for u in batch if notes_by_key.get(u["key"])
        )
        return (
            ch.tag("pm.stories", [u["key"] for u in batch]) + ch.locked_block(context) +
            "You are a senior product manager converting functional requirements into detailed user "
            "stories. Write ONE story per requirement below — no requirement skipped, none merged.\n\n"
            + ch.idea_block(context) +
            "\nRoles (use these exact names for `role`): " + ", ".join(role_names) +
            "\n\nRequirements:\n" + "\n".join(blocks) + "\n\n"
            "For each: a real \"As a <role>, I want <specific capability>, so that <concrete benefit>\" "
            "sentence (never generic filler), preconditions, trigger, a main flow of 4-6 concrete steps "
            "naming what the user does and what the system does, an alternative flow, an exception flow "
            "that says exactly what error the user sees, and 3-4 Given/When/Then acceptance criteria that "
            "test this requirement specifically (happy path, invalid input, permission denied, edge case). "
            "Use each requirement's exact name; echo its id in `fr_id`.\n\n"
            + revisions +
            "Respond ONLY with JSON in exactly this shape:\n" + STORY_SHAPE
        )

    items, stats = ch.generate_units(
        label="User stories", units=units, prev_by_key=prev_by_key, notes=notes, hash_of=hash_of,
        needles_of=needles_of, make_prompt=make_prompt, key_field="fr_id", list_key="stories",
        client=client, batch_size=5, max_tokens=9000,
    )

    stories = []
    first_story_of_module: dict[str, dict] = {}
    for r in reqs:
        raw = items[r["id"]]
        mid = r.get("module_id")
        brs = brs_by_mod.get(mid, [])
        story = {
            "id": us_of[r["id"]],
            "epic_id": epic_of.get(mid, ""),
            "feature": r["name"],
            "role": _norm_role(raw.get("role", ""), r.get("actor", ""), role_names),
            "story": raw.get("story", ""),
            "business_value": raw.get("business_value", ""),
            "preconditions": raw.get("preconditions", ""),
            "trigger": raw.get("trigger", ""),
            "main_flow": ch.as_str_list(raw.get("main_flow")),
            "alternative_flow": raw.get("alternative_flow", "None"),
            "exception_flow": raw.get("exception_flow", ""),
            "business_rules": [f"{b['id']}: {b['rule']}" for b in brs],
            "dependencies": [us_of[d] for d in r.get("dependencies", []) if d in us_of],
            "acceptance_criteria": ch.as_str_list(raw.get("acceptance_criteria")),
            "related_fr_ids": [r["id"]],
            "_src": raw.get("_src"),
        }
        stories.append(story)
        first_story_of_module.setdefault(mid, story)

    epics = [
        {"id": epic_of[m["id"]], "name": m["name"], "description": m.get("purpose", "")}
        for m in modules if any(r.get("module_id") == m["id"] for r in reqs)
    ]
    priorities = [
        {"story_id": us_of[r["id"]], "priority": PRIORITY_MAP.get(r.get("priority"), "Medium"),
         "notes": f"{r.get('priority')} — {r.get('rationale', '')}".strip(" —")}
        for r in reqs
    ]
    ch.report(f"User stories: {len(stories)} ({stats['generated']} generated, {stats['reused']} reused).")
    return {
        "summary": f"Converted {len(reqs)} functional requirements across {len(epics)} epics into "
                   f"{len(stories)} fully detailed user stories.",
        "epics": epics, "stories": stories, "priorities": priorities,
    }

"""
Chunked LIVE generation for the Business Analyst (BRD).

Pipeline (first run):
  1. plan        one call  -> modules (12-18), roles, personas, stakeholders
  2. narrative   one call  -> exec summary, background, problems, KPIs, scope,
                              journeys, release strategy, assumptions ...   } in
  3. module x N  N calls   -> 4-6 FRs + module detail + business rules +    } parallel
                              acceptance criteria for each module           }
  4. crosscut A/B two calls-> NFRs, data model, notifications, security,
                              privacy, integrations, risks, glossary ...
  5. assemble    code      -> global FR/BR IDs, MVP prioritization, story
                              summaries and the traceability matrix (all
                              derived, never re-invented by the model)

Revision run (a "Resolve issues" round): the plan, and every module chunk no
note names, are reused untouched; only implicated modules are regenerated,
new capabilities can be added as modules, and the narrative/core sections
are patched section-by-section.
"""

from __future__ import annotations

import json
import re

import chunked as ch
import content_kit as ck
from context import AgentRole, ProjectContext

ROLE = AgentRole.BUSINESS_ANALYST.value
MIN_MODULES = 10
HARD_MIN_MODULES = 8
MIN_FR = 3

# Sections a revision note may patch (module-derived sections are excluded:
# they change only by regenerating the module that owns them).
PATCHABLE = [
    "executive_summary", "business_background", "problem_statement", "product_vision",
    "business_objectives", "kpis", "scope_in", "scope_out", "non_goals", "stakeholders", "roles",
    "user_personas", "current_state_process", "current_state_flow", "future_state_process",
    "future_state_flow", "user_journeys", "release_strategy", "future_enhancements",
    "open_questions", "assumptions", "constraints", "dependencies", "glossary", "nfrs",
    "data_entities", "data_relationships", "data_classification", "notifications_matrix",
    "payment_requirements", "admin_operations", "reporting", "analytics_events",
    "security_requirements", "threats", "privacy_compliance", "accessibility", "integrations", "risks",
    "flow_diagrams", "key_parameters",
]

_NEW_MODULE_HINT = re.compile(r"no module or\s+functional requirement|add a dedicated module|not represented", re.I)

# ---------------------------------------------------------------------------
# JSON shapes (plain strings — no f-string brace escaping needed)
# ---------------------------------------------------------------------------
PLAN_SHAPE = """{
  "modules": [{"name": "...", "purpose": "one or two sentences"}],
  "roles": [{"role": "...", "purpose": "...", "responsibilities": "...", "capabilities": "...", "permissions": "...", "restricted": "..."}],
  "user_personas": [{"name": "...", "role": "exact role name", "occupation": "...", "goals": "...", "needs": "...", "pain_points": "...", "behaviors": "...", "expectations": "..."}],
  "stakeholders": [{"stakeholder": "...", "interest": "...", "authority": "..."}]
}"""

NARRATIVE_SHAPE = """{
  "summary": "one sentence overview of the product",
  "executive_summary": {"product": "...", "target_users": "...", "opportunity": "...", "solution": "...", "business_value": "...", "capabilities": ["..."]},
  "business_background": {"current_context": "...", "existing_process": "...", "market_situation": "...", "why_needed": "...", "current_limitations": "...", "business_opportunity": "..."},
  "problem_statement": [{"area": "...", "pain_point": "...", "impact": "..."}],
  "product_vision": {"vision": "...", "future_state": "...", "long_term_direction": "...", "value_proposition": "..."},
  "business_objectives": ["..."],
  "kpis": [{"kpi": "...", "definition": "...", "target": "... or TBD", "measurement": "..."}],
  "scope_in": ["..."], "scope_out": ["..."], "non_goals": ["..."],
  "current_state_process": "...", "current_state_flow": "Step 1 -> Step 2 -> ...",
  "future_state_process": "...", "future_state_flow": "Step 1 -> Step 2 -> ...",
  "user_journeys": {"<Role> Journey": "..."},
  "release_strategy": [{"phase": "...", "description": "...", "exit_criteria": "..."}],
  "future_enhancements": ["..."],
  "open_questions": ["..."],
  "assumptions": ["..."], "constraints": ["..."], "dependencies": ["..."]
}"""

MODULE_SHAPE = """{
  "modules": [{
    "module_id": "MOD-01",
    "requirements": [{
      "name": "short capability name", "description": "what the system must do, specific and testable",
      "actor": "exact role name", "priority": "P0|P1|P2|P3",
      "rationale": "why it exists, tied to the business need",
      "acceptance_consideration": "one sentence: when is it met",
      "source": "discovery answer / business idea / assumption",
      "depends_on_local": [0], "depends_on_modules": ["MOD-02"]
    }],
    "module_detail": {"purpose": "...", "actors": "...", "inputs": "...", "processing": "...", "outputs": "...", "business_rules": "...", "dependencies": "...", "priority": "..."},
    "business_rules": [{"rule": "a concrete, enforceable rule"}],
    "acceptance_criteria": ["Given ..., when ..., then ..."]
  }]
}"""

CROSS_A_SHAPE = """{
  "nfrs": [{"category": "...", "requirement": "...", "description": "...", "priority": "...", "measurement": "...", "target": "concrete target or 'TBD — Requires Business/Technical Confirmation'", "verification_method": "...", "related_module": "exact module name", "source": "..."}],
  "data_entities": [{"entity": "...", "fields": ["..."]}],
  "data_relationships": ["..."],
  "data_classification": [{"level": "Public|Internal|Confidential|Restricted", "examples": "...", "access": "..."}],
  "notifications_matrix": [{"event": "...", "customer": "Yes|No", "provider": "Yes|No", "admin": "Yes|No", "channel": "..."}],
  "reporting": [{"group": "...", "reports": ["..."]}],
  "analytics_events": ["..."]
}"""

CROSS_B_SHAPE = """{
  "payment_requirements": {"methods": "...", "flow": "...", "statuses": "...", "failure_retry": "...", "duplicate_prevention": "...", "refunds": "...", "reconciliation": "..."},
  "admin_operations": {"dashboard": "...", "user_management": "...", "content_management": "...", "configuration": "...", "audit": "..."},
  "security_requirements": ["..."],
  "threats": [{"threat": "...", "control": "..."}],
  "privacy_compliance": "...",
  "accessibility": ["..."],
  "integrations": [{"integration": "...", "purpose": "...", "requirements": "..."}],
  "risks": [{"risk": "...", "category": "...", "likelihood": "Low|Medium|High", "severity": "Low|Medium|High", "impact": "...", "consequence": "...", "mitigation": "a concrete control or action", "owner": "exact role name", "trigger": "the early-warning signal that this risk is materialising"}],
  "glossary": [{"term": "...", "definition": "..."}]
}"""


CROSS_C_SHAPE = """{
  "flow_diagrams": [{"title": "...", "description": "one sentence", "mermaid": "flowchart TD\\n    A[\\"Start\\"] --> B{\\"Decision?\\"}\\n    B -->|Yes| C[\\"Step\\"]\\n    B -->|No| D[\\"Other step\\"]"}],
  "key_parameters": [{"parameter": "...", "value": "a concrete value or 'TBD — needs business decision'", "status": "Proposed default|Confirmed|TBD", "related": "FR or BR ids", "owner": "exact role name"}]
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _module_lines(modules: list[dict]) -> str:
    return "\n".join(f"- {m['id']} {m['name']}: {m.get('purpose', '')}" for m in modules)


def _role_names(roles: list[dict]) -> list[str]:
    return [r.get("role", "") for r in roles if r.get("role")]


def _reference_checklist(context: ProjectContext) -> str:
    try:
        ref = ck.select_modules(context)
    except Exception:
        return "- (none)"
    return "\n".join(f"- {m['name']}: {m['purpose']}" for m in ref[:24]) or "- (none)"


def _reindex_modules(raw: list, start: int = 1) -> list[dict]:
    out = []
    for i, m in enumerate(raw, start):
        if isinstance(m, dict) and m.get("name"):
            out.append({"id": f"MOD-{i:02d}", "name": str(m["name"]).strip(), "purpose": str(m.get("purpose", "")).strip()})
    return out


def _normalize_priority(p) -> str:
    p = str(p or "").upper().strip()
    return p if p in ("P0", "P1", "P2", "P3") else "P1"


def _coerce_items(raw, fields: tuple[str, ...]) -> list[dict]:
    """A model — especially a smaller/lite one — sometimes flattens an item
    that was supposed to be an object into a plain string (e.g. a
    requirement as a bare sentence instead of {"name": ..., "description":
    ...}). Downstream code (_assign_ids in particular) does item["id"] = ...
    on every entry, which raises TypeError on a str. Rather than crash or
    silently drop the content, a string item is salvaged into a dict with
    the string copied into every one of `fields` (so whichever field a
    later reader looks at, e.g. "name" for a requirement or "rule" for a
    business rule, is populated) — imperfect structure, but the generated
    content survives. Anything that's neither a dict nor a non-empty string
    (None, a number, an empty string) is dropped."""
    out = []
    for it in ch.as_list(raw):
        if isinstance(it, dict):
            out.append(it)
        elif isinstance(it, str) and it.strip():
            out.append({f: it.strip() for f in fields})
    return out


# ---------------------------------------------------------------------------
# Stage 1 — plan
# ---------------------------------------------------------------------------
def _plan(context: ProjectContext, client) -> dict:
    prompt_base = (
        ch.tag("ba.plan") + ch.locked_block(context) +
        "You are a senior business analyst planning the structure of an enterprise-grade "
        "Business Requirements Document. Downstream AI agents will build user stories, a PRD and "
        "UX screens from the modules you define, so the module list must be complete and specific.\n\n"
        + ch.idea_block(context) +
        "\nReference capability checklist for this kind of product — a STARTING POINT only. Rename "
        "items to this product's own vocabulary, drop what plainly does not apply, and add what is "
        "specific to this product:\n" + _reference_checklist(context) + "\n\n"
        "Produce:\n"
        "- modules: 12 to 18 modules. Each is a distinct, user-visible capability area. Cover — where "
        "relevant to THIS product — registration/authentication/profile; the core business "
        "functionality split into 3-6 modules along its real sub-areas; search & discovery; "
        "dashboards/home; notifications; payments/billing/subscriptions; reviews/ratings; messaging; "
        "settings & privacy & account deletion; admin/back-office (moderation, disputes/support, user "
        "management); reporting & analytics; third-party integrations. Do NOT merge unrelated "
        "capabilities into one vague module.\n"
        "- roles: 3 to 6 roles with real permissions and restrictions. Use ONE consistent name per role "
        "everywhere; if a role has a common alias, define it in that role's purpose (e.g. \"Provider — "
        "the professional photographers\").\n"
        "- user_personas: 3 to 5, each tied to an exact role name.\n"
        "- stakeholders: 8 to 12.\n\n"
        "Respond ONLY with JSON in exactly this shape:\n" + PLAN_SHAPE
    )
    data = ch.call_json(client, prompt_base, max_tokens=7000)
    modules = _reindex_modules(data.get("modules", []))
    if len(modules) < MIN_MODULES:
        retry = (
            prompt_base + f"\n\nYour previous answer contained only {len(modules)} modules "
            f"({', '.join(m['name'] for m in modules)}). A complete specification for this product "
            "needs 12 to 18. Return the FULL JSON again with the missing capability areas added "
            "(keep the ones you already have)."
        )
        data = ch.call_json(client, retry, max_tokens=7000)
        modules = _reindex_modules(data.get("modules", []))
    if len(modules) < HARD_MIN_MODULES:
        raise RuntimeError(f"Business Analyst plan produced only {len(modules)} modules; expected 12-18.")
    roles = [r for r in ch.as_list(data.get("roles")) if isinstance(r, dict) and r.get("role")]
    if not roles:
        raise RuntimeError("Business Analyst plan produced no roles.")
    return {
        "modules": modules,
        "roles": roles,
        "user_personas": ch.as_list(data.get("user_personas")),
        "stakeholders": ch.as_list(data.get("stakeholders")),
    }


def _extend_modules(context: ProjectContext, client, modules: list[dict], notes: list[str]) -> list[dict]:
    prompt = (
        ch.tag("ba.extend_modules") + ch.locked_block(context) +
        "You are a senior business analyst. A validation step found that the product needs "
        "capabilities that no module covers.\n\n" + ch.idea_block(context) +
        "\nExisting modules:\n" + _module_lines(modules) +
        "\n\nValidation notes:\n" + "\n".join(f"- {n}" for n in notes) +
        "\n\nReturn ONLY the NEW modules needed (0 to 3) — never repeat or rename an existing "
        "module. Respond ONLY with JSON: {\"modules\": [{\"name\": \"...\", \"purpose\": \"...\"}]}"
    )
    data = ch.call_json(client, prompt, max_tokens=2000)
    start = max(ch.id_num(m["id"]) or 0 for m in modules) + 1
    return _reindex_modules(data.get("modules", [])[:3], start)


# ---------------------------------------------------------------------------
# Stage 2 — narrative
# ---------------------------------------------------------------------------
def _narrative(context: ProjectContext, client, plan: dict) -> dict:
    prompt = (
        ch.tag("ba.narrative") + ch.locked_block(context) +
        "You are a senior business analyst writing the narrative sections of an enterprise-grade "
        "Business Requirements Document. Be specific to this product and go deep — every list "
        "as long as the product warrants, never 2-3 token examples.\n\n" + ch.idea_block(context) +
        "\nModules:\n" + _module_lines(plan["modules"]) +
        "\n\nRoles (use these exact names): " + ", ".join(_role_names(plan["roles"])) +
        "\n\nMinimums: problem_statement 6+; business_objectives 5+; kpis 8+ (mark unknown targets "
        "TBD, never invent an authoritative number); scope_in 8+; scope_out 5+; non_goals 4+; "
        "user_journeys: one per role; release_strategy: 4-5 phases running from the first pilot "
        "through general availability; future_enhancements 6+; open_questions 4+; assumptions 5+; "
        "constraints 4+; dependencies 5+. State explicitly that applicable regulation must be "
        "confirmed for the launch geography if unknown — never invent a compliance claim.\n\n"
        "Respond ONLY with JSON in exactly this shape:\n" + NARRATIVE_SHAPE
    )
    return ch.call_json(client, prompt, max_tokens=9000)


# ---------------------------------------------------------------------------
# Stage 3 — per-module requirements
# ---------------------------------------------------------------------------
def _module_prompt_factory(context, plan):
    modules = plan["modules"]
    roles = plan["roles"]

    def make_prompt(batch, notes_by_key, prev_by_key):
        m = batch[0]["module"]
        key = m["id"]
        return (
            ch.tag("ba.module", [key]) + ch.locked_block(context) +
            "You are a senior business analyst writing the requirements for ONE module of a "
            "Business Requirements Document.\n\n" + ch.idea_block(context) +
            "\nAll modules (for cross-module dependencies):\n" + _module_lines(modules) +
            "\n\nRoles (use these exact names for `actor`): " + ", ".join(_role_names(roles)) +
            f"\n\nTHIS module: {m['id']} — {m['name']}: {m.get('purpose', '')}\n\n"
            "Write:\n"
            "- requirements: 4 to 6 functional requirements, each a DISTINCT, testable capability "
            "that belongs to this module (CRUD on its entities, state changes, validation, "
            "permissions, failure paths, notifications it triggers). Every permission a role has in "
            "this module must be backed by a requirement. Priorities must be realistic, not all P0: "
            "P0 = the product cannot launch without it, P1 = important for launch, P2 = valuable but "
            "deferrable to a second phase, P3 = nice-to-have/future. For an essential module (auth, "
            "the core transaction) most are P0/P1; for a supporting module include P2/P3 items.\n"
            "  depends_on_local = indexes (0-based) of OTHER requirements in this list this one needs; "
            "depends_on_modules = ids of other modules whose functionality it needs.\n"
            "- module_detail: purpose, actors, inputs, processing, outputs, business_rules, "
            "dependencies, priority.\n"
            "- business_rules: 2 to 4 concrete, enforceable rules for this module.\n"
            "- acceptance_criteria: 3 to 4 Given/When/Then statements.\n\n"
            + ch.revision_block(notes_by_key.get(key, []), ch.clean(prev_by_key[key]) if key in prev_by_key else None) +
            "Respond ONLY with JSON in exactly this shape (module_id must be \"" + key + "\"):\n" + MODULE_SHAPE
        )
    return make_prompt


def _build_module_chunks(context, client, plan, prev_chunks, notes):
    units = [{"key": m["id"], "module": m} for m in plan["modules"]]
    role_names = _role_names(plan["roles"])
    make_prompt = _module_prompt_factory(context, plan)

    def hash_of(u):
        return ch.fingerprint([u["module"], role_names, context.business_idea_raw])

    def needles_of(u):
        m = u["module"]
        prev = prev_chunks.get(m["id"], {})
        ids = [m["id"]] + [r.get("id") for r in prev.get("requirements", [])] + [b.get("id") for b in prev.get("business_rules", [])]
        return ids, [m["name"]]

    kwargs = dict(label="Requirements per module", units=units, prev_by_key=prev_chunks, notes=notes,
                  hash_of=hash_of, needles_of=needles_of, make_prompt=make_prompt,
                  key_field="module_id", list_key="modules", client=client, batch_size=1, max_tokens=7000)
    chunks, stats = ch.generate_units(**kwargs)
    for v in chunks.values():
        v["requirements"] = _coerce_items(v.get("requirements"), ("name", "description"))
        v["business_rules"] = _coerce_items(v.get("business_rules"), ("rule",))

    # A module that came back too thin gets one targeted regeneration.
    thin = [u for u in units if len(chunks[u["key"]].get("requirements", []) or []) < MIN_FR]
    if thin:
        fix_notes = [f"{u['module']['name']}: you returned too few functional requirements — write 4 to 6." for u in thin]
        redo, _ = ch.generate_units(**{**kwargs, "label": "Thin modules", "units": thin, "prev_by_key": {}, "notes": fix_notes})
        for k, v in redo.items():
            if len(v.get("requirements", []) or []) >= MIN_FR:
                chunks[k] = v
    still_thin = [k for k, v in chunks.items() if len(v.get("requirements", []) or []) < 1]
    if still_thin:
        raise RuntimeError(f"Business Analyst produced no requirements for modules {still_thin}.")
    return chunks, stats


# ---------------------------------------------------------------------------
# Stage 4 — cross-cutting sections
# ---------------------------------------------------------------------------
def _crosscut(context, client, plan, requirements):
    fr_lines = "\n".join(f"- {r['id']} [{r['module']}] {r['name']}" for r in requirements)
    common = (
        ch.locked_block(context) + ch.idea_block(context) +
        "\nModules:\n" + _module_lines(plan["modules"]) +
        "\n\nRoles: " + ", ".join(_role_names(plan["roles"])) +
        "\n\nFunctional requirements already defined:\n" + fr_lines + "\n\n"
    )
    a = (
        ch.tag("ba.crosscut_a") +
        "You are a senior business analyst writing the data, quality and notification sections of a "
        "Business Requirements Document.\n\n" + common +
        "Minimums: nfrs 14+ spanning performance, scalability, availability, reliability, security, "
        "privacy, accessibility, usability, maintainability, compatibility, monitoring, logging, "
        "backup/disaster-recovery, localization (each with a measurement, a concrete target or an "
        "explicit TBD, a verification method and the exact related module name); data_entities 10+ "
        "with realistic key fields; data_relationships 6+; data_classification: all four levels; "
        "notifications_matrix 20+ rows covering every important business event; reporting 4+ groups; "
        "analytics_events 8+.\n\nRespond ONLY with JSON in exactly this shape:\n" + CROSS_A_SHAPE
    )
    b = (
        ch.tag("ba.crosscut_b") +
        "You are a senior business analyst writing the operations, security and risk sections of a "
        "Business Requirements Document.\n\n" + common +
        "Minimums: security_requirements 8+; threats 6+; accessibility 6+ (target WCAG 2.2 AA unless "
        "told otherwise); integrations 4+; risks 10+; glossary 15+ terms — including every actor/role "
        "alias used anywhere (e.g. \"Provider = the professional photographers\") so a synonym is a "
        "documented alias, not an inconsistency. If the product has no payments at all, set "
        "payment_requirements to null. Never invent a compliance claim; say applicable regulation "
        "must be confirmed for the launch geography.\n\n"
        "RISK ASSESSMENT RULES: every risk must be specific to THIS product (not generic boilerplate) and "
        "carry a likelihood AND a severity (Low/Medium/High, judged honestly — not everything is High), "
        "an owner (one of the exact role names above), and a trigger (the observable early-warning "
        "signal). A mitigation must be a concrete control or action, never just 'build the feature'. "
        "Cover, where relevant: fraud/chargebacks/abuse, third-party API or vendor changes, "
        "delivery/logistics/supply, regulatory & consent compliance, availability/performance, "
        "customer-retention/churn, data security & privacy, operational capacity, and product-specific "
        "safety or quality risks.\n\nRespond ONLY with JSON in exactly this shape:\n"
        + CROSS_B_SHAPE
    )
    c = (
        ch.tag("ba.crosscut_c") +
        "You are a senior business analyst adding two things to a Business Requirements Document.\n\n" + common +
        "1. flow_diagrams: 4-6 envisioned flow diagrams as VALID Mermaid `flowchart TD` source covering the "
        "core end-to-end user journey, the main transaction/checkout or booking flow (with its failure "
        "branch), any recurring/subscription/lifecycle flow, the return/refund/dispute or support flow, "
        "and the admin/operations fulfilment flow — whichever apply to THIS product. Each: 6-14 nodes, "
        "at least one decision diamond, node text in double quotes with NO parentheses or special "
        "characters inside labels, and the mermaid field a single string with \\n line breaks.\n"
        "2. key_parameters: 12+ concrete business parameters the requirements depend on (session timeout, "
        "password policy, payment/refund/return windows, delivery or lead-time SLAs, order/quantity "
        "limits, retention periods, retry counts, thresholds, fees...). Give a sensible proposed default "
        "value with status 'Proposed default', or 'TBD — needs business decision' with status TBD when "
        "it depends on facts you do not have. Never present an invented number as confirmed.\n\n"
        "Respond ONLY with JSON in exactly this shape:\n" + CROSS_C_SHAPE
    )

    def safe_c():
        try:
            return ch.call_json(client, c, max_tokens=7000)
        except ch.LLMTruncated:
            return {}
        except RuntimeError:
            return {}  # depth extras must never fail the whole BRD; the code fallbacks + validation cover it

    ra, rb, rc = ch.run_parallel("Cross-cutting sections", [
        lambda: ch.call_json(client, a, max_tokens=9000),
        lambda: ch.call_json(client, b, max_tokens=9000),
        safe_c,
    ])
    return {**ra, **rb, **(rc or {})}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _assign_ids(order, chunks, reused, prev_ids, list_key, prefix, width=3):
    """Gives every item of every module a global ID. A regenerated module keeps
    its previous IDs positionally (so downstream references stay valid) and any
    extra items get fresh IDs above the current maximum; a reused module keeps
    its items untouched. On a first run IDs are sequential in module order."""
    existing = [n for ids in prev_ids.values() for i in ids if (n := ch.id_num(i)) is not None]
    counter = (max(existing) if existing else 0) + 1
    for mid in order:
        if mid in reused:
            continue
        old = list(prev_ids.get(mid, []))
        for item in chunks[mid].get(list_key, []):
            if not isinstance(item, dict):
                continue  # defensive: should already be sanitized upstream
            if old:
                item["id"] = old.pop(0)
            else:
                item["id"] = ch.make_id(prefix, counter, width)
                counter += 1


def _assemble(context, plan, narrative, chunks, reused, prev_out, cross, notes_patch=None) -> dict:
    modules = plan["modules"]
    order = [m["id"] for m in modules]
    name_of = {m["id"]: m["name"] for m in modules}

    prev_fr_ids = {}
    prev_br_ids = {}
    for r in prev_out.get("requirements", []):
        prev_fr_ids.setdefault(r.get("module_id"), []).append(r["id"])
    for b in prev_out.get("business_rules", []):
        prev_br_ids.setdefault(b.get("module_id"), []).append(b["id"])
    _assign_ids(order, {k: {"requirements": v.get("requirements", [])} for k, v in chunks.items()},
                reused, prev_fr_ids, "requirements", "FR")
    _assign_ids(order, {k: {"business_rules": v.get("business_rules", [])} for k, v in chunks.items()},
                reused, prev_br_ids, "business_rules", "BR")

    requirements, business_rules, module_details, acceptance = [], [], [], []
    for mid in order:
        chunk = chunks[mid]
        mname = name_of[mid]
        local_ids = [r["id"] for r in chunk.get("requirements", [])]
        for r in chunk.get("requirements", []):
            if "depends_on_local" not in r and "depends_on_modules" not in r and "dependencies" in r:
                deps = list(r.get("dependencies") or [])  # already resolved (a reused module)
            else:
                deps = []
                for idx in ch.as_list(r.get("depends_on_local")):
                    if isinstance(idx, int) and 0 <= idx < len(local_ids) and local_ids[idx] != r["id"]:
                        deps.append(local_ids[idx])
                for dep_mid in ch.as_list(r.get("depends_on_modules")):
                    target = chunks.get(dep_mid)
                    if dep_mid != mid and target and target.get("requirements"):
                        fid = target["requirements"][0].get("id")
                        if fid and fid not in deps:
                            deps.append(fid)
            requirements.append({
                "id": r["id"], "name": r.get("name", ""), "description": r.get("description", ""),
                "actor": r.get("actor", ""), "priority": _normalize_priority(r.get("priority")),
                "module": mname, "module_id": mid,
                "rationale": r.get("rationale", ""), "dependencies": deps,
                "acceptance_consideration": r.get("acceptance_consideration", ""),
                "status": "Draft — pending stakeholder confirmation",
                "source": r.get("source", "business idea / discovery answers"),
            })
        for b in chunk.get("business_rules", []):
            business_rules.append({"id": b["id"], "rule": b.get("rule", ""), "module": mname, "module_id": mid})
        detail = dict(chunk.get("module_detail") or {})
        detail.setdefault("purpose", next(m["purpose"] for m in modules if m["id"] == mid))
        detail["module"] = mname
        detail["module_id"] = mid
        module_details.append(detail)
        if chunk.get("acceptance_criteria"):
            acceptance.append({"capability": mname, "criteria": ch.as_str_list(chunk["acceptance_criteria"])})

    # --- derived sections: computed from the requirements, never re-invented ---
    tiers = {"P0": [], "P1": [], "P2": [], "P3": []}
    for r in requirements:
        tiers[r["priority"]].append(f"{r['id']} — {r['name']}")
    narrative_scope_out = list(narrative.get("scope_out", []))
    mvp_prioritization = {**tiers, "out_of_scope": narrative_scope_out}

    stories_summary = []
    traceability = []
    for r in requirements:
        n = ch.id_num(r["id"]) or 0
        sid = ch.make_id("US", n)
        stories_summary.append({
            "id": sid, "title": r["name"], "actor": r["actor"],
            "story": f"As a {r['actor'] or 'user'}, I want to use the \u201c{r['name']}\u201d capability, so that "
                     f"{(r['rationale'] or 'the business need is met').rstrip('.')}.",
            "priority": r["priority"], "related_fr": r["id"],
        })
        traceability.append({
            "brd_area": r["module"], "fr": r["id"], "user_story": sid, "module": r["module"],
            "qa_reference": ch.make_id("QA", n), "priority": r["priority"],
        })

    exec_sum = narrative.get("executive_summary") or {}
    out = {
        "summary": (narrative.get("summary") or "Business requirements generated").rstrip(".") +
                   f" ({len(modules)} modules, {len(requirements)} functional requirements, "
                   f"{len(business_rules)} business rules).",
        "target_users": exec_sum.get("target_users", "") if isinstance(exec_sum, dict) else "",
        "modules": modules, "roles": plan["roles"], "user_personas": plan["user_personas"],
        "stakeholders": plan["stakeholders"],
        "requirements": requirements, "module_details": module_details, "business_rules": business_rules,
        "acceptance_criteria_summary": acceptance,
        "mvp_prioritization": mvp_prioritization,
        "user_stories_summary": stories_summary, "traceability_matrix": traceability,
        "success_metrics": [f"{k.get('kpi', '')}: {k.get('target', 'TBD')}" for k in narrative.get("kpis", []) if isinstance(k, dict)],
    }
    for key, value in narrative.items():
        if key not in out and key != "summary":
            out[key] = value
    for key, value in cross.items():
        if key == "nfrs":
            out["nfrs"] = [{**n, "id": ch.make_id("NFR", i), "dependencies": n.get("dependencies", []),
                            "status": "Draft — pending confirmation"} for i, n in enumerate(value or [], 1)]
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def generate(context: ProjectContext, client) -> dict:
    previous = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    prev_out = previous.output if previous else {}
    all_notes = list(context.resolution_notes or [])
    notes = ch.notes_for_document(all_notes, ROLE)
    revising = bool(prev_out.get("requirements"))

    # -- plan ---------------------------------------------------------------
    if revising:
        plan = {k: prev_out.get(k, []) for k in ("modules", "roles", "user_personas", "stakeholders")}
        if notes and any(_NEW_MODULE_HINT.search(n) for n in notes):
            ch.report("Adding missing modules…")
            plan["modules"] = plan["modules"] + _extend_modules(context, client, plan["modules"], notes)
    else:
        ch.report("Planning modules, roles and personas…")
        plan = _plan(context, client)

    # -- prior chunks (rebuilt from the previous output, per module) -----------
    prev_chunks: dict[str, dict] = {}
    if revising:
        by_mod_fr, by_mod_br = {}, {}
        for r in prev_out.get("requirements", []):
            by_mod_fr.setdefault(r.get("module_id"), []).append(r)
        for b in prev_out.get("business_rules", []):
            by_mod_br.setdefault(b.get("module_id"), []).append(b)
        details = {d.get("module_id"): d for d in prev_out.get("module_details", [])}
        criteria = {c["capability"]: c["criteria"] for c in prev_out.get("acceptance_criteria_summary", [])}
        src = prev_out.get("_chunk_src", {})
        for m in plan["modules"]:
            mid = m["id"]
            if mid in by_mod_fr:
                prev_chunks[mid] = {
                    "requirements": by_mod_fr[mid], "business_rules": by_mod_br.get(mid, []),
                    "module_detail": {k: v for k, v in details.get(mid, {}).items() if k not in ("module", "module_id")},
                    "acceptance_criteria": criteria.get(m["name"], []), "_src": src.get(mid),
                }

    # -- narrative + module chunks (parallel) -----------------------------------
    narrative = {k: prev_out[k] for k in ch.as_list(prev_out.get("_narrative_keys")) if k in prev_out} if revising else {}
    prev_narrative_summary = prev_out.get("summary", "")

    ch.report("Writing narrative sections and per-module requirements…")
    chunk_holder = {}

    def do_modules():
        chunk_holder["chunks"], chunk_holder["stats"] = _build_module_chunks(context, client, plan, prev_chunks, notes)

    def do_narrative():
        if not revising:
            chunk_holder["narrative"] = _narrative(context, client, plan)

    ch.run_parallel("Business Analyst", [do_modules, do_narrative], workers=2)
    chunks, stats = chunk_holder["chunks"], chunk_holder["stats"]
    if not revising:
        narrative = chunk_holder["narrative"]

    reused_modules = {mid for mid, c in chunks.items() if prev_chunks.get(mid) is c}

    # -- requirements now exist: cross-cutting sections ---------------------------
    if revising:
        cross = {k: prev_out[k] for k in ("nfrs", "data_entities", "data_relationships", "data_classification",
                                          "notifications_matrix", "reporting", "analytics_events",
                                          "payment_requirements", "admin_operations", "security_requirements",
                                          "threats", "privacy_compliance", "accessibility", "integrations",
                                          "risks", "glossary", "flow_diagrams", "key_parameters") if k in prev_out}
    else:
        # IDs must exist before the cross-cutting prompt lists FRs, so assign them first
        tmp = _assemble(context, plan, narrative, chunks, set(), {}, {})
        ch.report("Writing data model, NFRs, security and risks…")
        cross = _crosscut(context, client, plan, tmp["requirements"])

    out = _assemble(context, plan, narrative, chunks, reused_modules, prev_out, cross)

    # -- revision: patch narrative/core sections the notes concern --------------
    if revising and notes:
        _patch_core(context, client, out, notes)
        out["mvp_prioritization"]["out_of_scope"] = list(out.get("scope_out", []))
    if revising:
        out["summary"] = _summary_with_counts(prev_narrative_summary, out)

    _finalize_depth_sections(out)

    # chunk fingerprints + which top-level keys are narrative (for the next revision)
    out["_chunk_src"] = {mid: c.get("_src") for mid, c in chunks.items()}
    out["_narrative_keys"] = [k for k in narrative.keys() if k != "summary"]
    for k in out["_narrative_keys"]:
        out.setdefault(k, narrative[k])
    ch.report(f"Business requirements: {len(out['modules'])} modules, {len(out['requirements'])} FRs "
              f"({stats['generated']} module(s) generated, {stats['reused']} reused).")
    return out


def _finalize_depth_sections(out: dict) -> None:
    """Code-side guarantees for the depth sections, applied on every run/revision:
    risks get a derived rating and are ranked; flow diagrams are validated with a
    deterministic fallback built from the future/current-state flow text; key
    parameters are normalised."""
    out["risks"] = ch.normalize_risks(out.get("risks"))
    out["flow_diagrams"] = ch.normalize_flow_diagrams(
        out.get("flow_diagrams"),
        [("Envisioned future-state flow", out.get("future_state_flow", "")),
         ("Current-state flow (as-is)", out.get("current_state_flow", ""))],
    )
    out["key_parameters"] = ch.normalize_key_parameters(out.get("key_parameters"))


def _summary_with_counts(summary: str, out: dict) -> str:
    base = re.sub(r"\s*\(\d+ modules, \d+ functional requirements, \d+ business rules\)\.?$", "", summary or "").rstrip(".")
    return (f"{base} ({len(out['modules'])} modules, {len(out['requirements'])} functional requirements, "
            f"{len(out['business_rules'])} business rules).")


def _patch_core(context, client, out: dict, notes: list[str]) -> None:
    current = {k: out[k] for k in PATCHABLE if k in out}
    prompt = (
        ch.tag("ba.revise_core") + ch.locked_block(context) +
        "You are a senior business analyst revising a Business Requirements Document after a "
        "validation review. Below are the review's findings and the CURRENT content of the sections "
        "you may edit.\n\nFindings:\n" + "\n".join(f"- {n}" for n in notes) +
        "\n\nCurrent sections:\n" + json.dumps(current, indent=1, default=str) +
        "\n\nReturn ONLY the sections that must change to resolve the findings, each as a COMPLETE "
        "replacement value in the same JSON type it has now (a list stays a list). Change nothing "
        "the findings do not require — keep names, IDs and wording of everything else. Define every "
        "role alias in the glossary rather than leaving synonyms undefined. If none of the findings "
        "concern these sections, return {\"changes\": {}}.\n"
        "Respond ONLY with JSON: {\"changes\": {\"<section>\": <new value>}}"
    )
    data = ch.call_json(client, prompt, max_tokens=9000)
    ch.apply_section_patch(out, data.get("changes"), PATCHABLE)

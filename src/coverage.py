"""
coverage.py — deterministic, code-computed completeness & traceability
engine used by the AI Handoff Validation agent and the orchestrator's
automatic gap-correction loop.

Why this exists: an LLM asked to "check completeness" can be talked (or
simply drift) into saying a package is fine when it isn't. Everything in
this module is instead computed by matching IDs and keywords across the
four upstream documents' actual structured output
(agent_contributions[*].output) — Business Requirements, User Stories,
PRD, UX/Product Flow — so a capability can never be marked complete just
because a model said so. It has to be genuinely traceable end-to-end:

    Capability (BRD module)
      -> Business Requirement (FR-xxx)
        -> User Story (references that FR id)
        -> PRD Functional Requirement (same FR id, reused not renumbered)
        -> UX Screen / Flow (references that FR id)
        -> Technical Requirement (module mentioned in the PRD's technical section)
        -> Security Requirement (module mentioned in the PRD's security section)

This module has no side effects and works identically whether the
upstream agents ran in MOCK or LIVE mode, because both produce the same
JSON shape (modules / requirements["module"] / stories["related_fr_ids"] /
functional_requirements["id"] / screens["related_requirement_ids"]).
"""
from __future__ import annotations

from context import AgentRole, ProjectContext

COMPLETE = "✅ Complete"
PARTIAL = "⚠️ Partial"
MISSING = "❌ Missing"
NOT_APPLICABLE = "N/A"

_BLOCKING = (PARTIAL, MISSING)

# ---------------------------------------------------------------------------
# 1. Business-idea / discovery-answer capability keyword scan
# ---------------------------------------------------------------------------
# Used to catch a capability the business idea or discovery answers
# clearly imply that never made it into a module/requirement at all —
# the case content-derived ID matching alone can't catch, since there's
# nothing to match against if it's missing entirely.

CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Registration & Authentication": ("sign up", "signup", "register", "login", "log in", "create an account", "authenticate"),
    "User Profile": ("profile", "account settings"),
    "Roles & Permissions": ("role", "permission", "moderator", "access control"),
    "Onboarding": ("onboarding", "getting started", "walkthrough", "tutorial", "first-time user", "first time user"),
    "Search / Filter / Sort": ("search", "filter", "sort", "browse"),
    "Notifications & Alerts": ("notif", "alert", "reminder", "push"),
    "Payments / Billing": ("pay", "checkout", "invoice", "billing"),
    "Subscription": ("subscription", "recurring billing", "membership plan", "monthly plan", "plan tier", "free trial"),
    "Reports & Analytics": ("report", "analytic", "insight"),
    "Data Export/Import": ("export", "import their", "csv", "bulk upload", "download my data", "download their data"),
    "Third-Party Integrations": ("integrat", "connect to", "connect their", "sync with", "sync their", "calendar", "webhook", "api access", "third-party", "third party"),
    "AI / ML Functionality": ("artificial intelligence", "machine learning", " ai ", "ai-powered", "ai powered", "recommend", "personali", "predict", "smart match", "auto-generat", "chatbot", " nlp", "assistant"),
    "Offline / Sync": ("offline", "no internet", "airplane mode", "spotty", "poor connectivity", "low connectivity"),
    "Admin / Back Office": ("admin", "back office", "operations console", "moderation"),
    "Privacy / Data Retention / Account Deletion": ("delete my account", "delete their account", "account deletion", "data retention", "gdpr", "ccpa", "right to be forgotten", "consent"),
    "Compliance": ("compliance", "regulat", "hipaa", "pci", "sox"),
    "Accessibility": ("accessib", "wcag", "screen reader"),
    "Performance / Scalability": ("scale", "scalab", "high volume", "concurrent users"),
}

# Only used to decide whether a scanned capability is already represented
# by SOME module in the generated Business Requirements (a loose,
# additional safety net on top of the ID-based matrix below — it can only
# ever ADD a gap for the agents to fix, never hide one).
_CAPABILITY_MODULE_HINTS: dict[str, tuple[str, ...]] = {
    "AI / ML Functionality": ("ai", "recommend", "smart", "personali", "predict", "assist", "generat"),
    "Data Export/Import": ("export", "import"),
    "Third-Party Integrations": ("integrat", "connect"),
    "Offline / Sync": ("offline", "sync"),
    "Subscription": ("subscription", "billing", "plan"),
    "Onboarding": ("onboard",),
    "Privacy / Data Retention / Account Deletion": ("privacy", "consent", "retention", "deletion"),
}


def scan_idea_for_capabilities(context: ProjectContext) -> set[str]:
    """Capability labels whose keywords appear in the raw business idea OR
    any discovery ANSWER — deliberately the same text a discovery question
    would have been answered from, and NOT the question text itself (a
    question can mention a word like "third party" while asking about
    something else entirely, e.g. shipping carriers rather than software
    integrations — only what the business idea/answers actually assert
    should count). This also keeps this scan aligned with content_kit's
    own module-selection keyword scan, so the two can't disagree about
    what the business idea implies."""
    parts = [context.business_idea_raw or ""]
    for q in context.discovery_questions:
        if q.answer:
            parts.append(str(q.answer))
    haystack = f" {' '.join(parts).lower()} "

    return {cap for cap, keywords in CAPABILITY_KEYWORDS.items() if any(kw in haystack for kw in keywords)}


# ---------------------------------------------------------------------------
# 2. Cross-document, ID-based coverage matrix
# ---------------------------------------------------------------------------

# NOTE: the Business Analyst's "modules" list in its output only carries
# {id, name, purpose} in BOTH mock and LIVE mode — there is no reliable
# internal module "key" to match against once a document round-trips
# through JSON (and LIVE mode's LLM invents its own module names anyway).
# So the classifications below are keyword-based against the module's
# NAME + PURPOSE text rather than against content_kit's internal keys —
# this works the same way regardless of mode.

# A module is legitimately cross-cutting (its effect shows up on every
# screen rather than one dedicated screen of its own) if its name/purpose
# matches one of these phrase sets — a missing UX mapping there is
# N/A-with-reason, not a gap.
_NO_DEDICATED_UX_HINTS = ("security", "access control", "rbac", "role-based access")

# A module inherently carries technical detail beyond the PRD's generic
# platform-wide technical section if its name/purpose matches one of
# these phrase sets; if the PRD's technical section doesn't mention it at
# all, that's treated as a real gap rather than globally-covered.
_REQUIRES_DISTINCT_TECHNICAL_HINTS = (
    "payment", "billing", "ai-powered", "ai powered", "artificial intelligence", "machine learning",
    "recommend", "integrat", "third-party", "third party", "offline", "sync",
    "scheduling", "availability", "trust & safety", "trust and safety",
    "escrow", "dispute", "fulfil", "shipment", "delivery", "export", "import",
    "subscription", "plan management",
)

# A module inherently carries security/privacy detail beyond the PRD's
# generic platform-wide security section if its name matches one of these
# phrase sets.
_REQUIRES_DISTINCT_SECURITY_HINTS = (
    "authentication", "account management", "payment", "billing", "profile",
    "trust & safety", "trust and safety", "admin & operations", "operations console",
    "back office", "ai-powered", "ai powered", "artificial intelligence", "machine learning",
    "recommend", "privacy", "consent", "data retention", "subscription", "plan management",
    "integrat", "third-party", "third party",
)


def _matches_any(text: str, hints: tuple[str, ...]) -> bool:
    """Word/phrase-boundary match — plain substring matching would let
    short or common tokens false-positive inside unrelated words (e.g.
    the hint "ai" inside "availability", or "admin" inside a sentence that
    merely mentions Admin as an actor rather than being about the Admin
    module itself)."""
    import re
    for h in hints:
        pattern = r"(?<![a-z0-9])" + re.escape(h.strip()) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def _text_blob(*parts) -> str:
    out = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, (list, tuple, set)):
            out.append(_text_blob(*p))
        elif isinstance(p, dict):
            out.append(_text_blob(*p.values()))
        else:
            out.append(str(p))
    return " ".join(out).lower()


def _mentions_module(blob: str, mod_name: str, module_key: str | None) -> bool:
    name = (mod_name or "").strip().lower()
    if len(name) > 3 and name in blob:
        return True
    if module_key:
        key_phrase = module_key.replace("_", " ").strip()
        if len(key_phrase) > 3 and key_phrase in blob:
            return True
    return False


def compute_coverage_matrix(context: ProjectContext) -> dict:
    """Builds the capability x document coverage matrix for the AI
    Handoff Validation report, purely from the 4 upstream agents'
    structured output — no LLM call here. Returns a dict with:

      rows: one row per capability/module with ✅/⚠️/❌/N/A per document
      totals: counts + an overall coverage percentage
      missing_capabilities / partial_capabilities: capability names with
        at least one ❌ / ⚠️ (excluding N/A) somewhere in their row
      unmapped_idea_capabilities: capabilities the business idea/answers
        clearly imply that have no representation in the BRD at all
    """
    ba = context.get_contribution(AgentRole.BUSINESS_ANALYST)
    pm = context.get_contribution(AgentRole.PRODUCT_MANAGER)
    prd = context.get_contribution(AgentRole.PRODUCT_REQUIREMENTS)
    ux = context.get_contribution(AgentRole.UX_PRODUCT_FLOW)

    ba_o = ba.output if ba else {}
    pm_o = pm.output if pm else {}
    prd_o = prd.output if prd else {}
    ux_o = ux.output if ux else {}

    modules = list(ba_o.get("modules", []))
    requirements = [r for r in ba_o.get("requirements", []) if isinstance(r, dict)]
    stories = [s for s in pm_o.get("stories", []) if isinstance(s, dict)]
    prd_frs = [f for f in prd_o.get("functional_requirements", []) if isinstance(f, dict)]
    screens = [s for s in ux_o.get("screens", []) if isinstance(s, dict)]
    flows = [f for f in ux_o.get("user_flows", []) if isinstance(f, dict)]

    prd_fr_ids = {fr.get("id") for fr in prd_frs if fr.get("id")}
    story_fr_ids: set[str] = set()
    for s in stories:
        story_fr_ids.update(s.get("related_fr_ids", []) or [])
    ux_fr_ids: set[str] = set()
    for scr in screens:
        ux_fr_ids.update(scr.get("related_requirement_ids", []) or [])
    for fl in flows:
        ux_fr_ids.update(fl.get("related_requirement_ids", []) or [])

    technical_blob = _text_blob(
        prd_o.get("technical_integration_constraints"),
        prd_o.get("non_functional_requirements"),
        ba_o.get("nfrs"),
        ba_o.get("integrations"),
    )
    security_blob = _text_blob(
        prd_o.get("security_privacy_access_constraints"),
        ba_o.get("security_requirements"),
        ba_o.get("threats"),
        ba_o.get("privacy_compliance"),
    )

    frs_by_module_name: dict[str, list] = {}
    for r in requirements:
        mod = r.get("module") or "Unspecified module"
        frs_by_module_name.setdefault(mod, []).append(r)

    if not modules:
        # LIVE mode always produces a "modules" list; this only guards a
        # partially-run/degenerate context so the matrix doesn't explode.
        modules = [{"id": f"MOD-{i:02d}", "name": name, "purpose": ""} for i, name in enumerate(sorted(frs_by_module_name.keys()), start=1)]

    rows = []
    missing_capabilities = []
    partial_capabilities = []

    for m in modules:
        mod_name = m.get("name") or "Unspecified module"
        module_key = m.get("key")  # present only for informational purposes if an upstream doc happens to include it
        # Classification uses the module NAME only, not its purpose prose —
        # purpose text is free-form and often mentions other actors/concepts
        # in passing (e.g. "...and Admins moderate flagged content"), which
        # would false-positive-match hints meant to identify a different
        # module entirely.
        name_blob = mod_name.lower()
        frs = frs_by_module_name.get(mod_name, [])
        fr_ids = {r.get("id") for r in frs if r.get("id")}

        brd_status = COMPLETE if fr_ids else MISSING

        if not fr_ids:
            prd_status = story_status = ux_status = MISSING
        else:
            prd_hit = fr_ids & prd_fr_ids
            prd_status = COMPLETE if prd_hit == fr_ids else (PARTIAL if prd_hit else MISSING)
            story_hit = fr_ids & story_fr_ids
            story_status = COMPLETE if story_hit == fr_ids else (PARTIAL if story_hit else MISSING)
            ux_hit = fr_ids & ux_fr_ids
            ux_status = COMPLETE if ux_hit == fr_ids else (PARTIAL if ux_hit else MISSING)

        notes = []
        if ux_status == MISSING and _matches_any(name_blob, _NO_DEDICATED_UX_HINTS):
            ux_status = NOT_APPLICABLE
            notes.append("Cross-cutting capability enforced on every screen rather than shown on a dedicated screen of its own.")

        needs_tech = _matches_any(name_blob, _REQUIRES_DISTINCT_TECHNICAL_HINTS)
        if _mentions_module(technical_blob, mod_name, module_key):
            technical_status = COMPLETE
        elif needs_tech:
            technical_status = MISSING
        else:
            technical_status = NOT_APPLICABLE
            notes.append("Covered by the PRD's global technical/non-functional requirements rather than a capability-specific entry.")

        needs_sec = _matches_any(name_blob, _REQUIRES_DISTINCT_SECURITY_HINTS)
        if _mentions_module(security_blob, mod_name, module_key):
            security_status = COMPLETE
        elif needs_sec:
            security_status = MISSING
        else:
            security_status = NOT_APPLICABLE
            notes.append("Covered by the PRD's global security & access-control section rather than a capability-specific entry.")

        rows.append({
            "capability": mod_name,
            "module_key": module_key,
            "fr_ids": sorted(fr_ids),
            "brd": brd_status,
            "prd": prd_status,
            "user_story": story_status,
            "ux": ux_status,
            "technical": technical_status,
            "security": security_status,
            "notes": notes,
        })

        statuses = (brd_status, prd_status, story_status, ux_status, technical_status, security_status)
        if MISSING in statuses:
            missing_capabilities.append(mod_name)
        elif PARTIAL in statuses:
            partial_capabilities.append(mod_name)

    # --- Idea-text capabilities with no module representation at all ---
    unmapped_idea_capabilities = []
    scanned = scan_idea_for_capabilities(context)
    module_blob = _text_blob([m.get("name", "") for m in modules]) + " " + _text_blob([m.get("key", "") for m in modules if m.get("key")])
    for cap in sorted(scanned):
        hints = _CAPABILITY_MODULE_HINTS.get(cap)
        if hints and not any(h in module_blob for h in hints):
            unmapped_idea_capabilities.append(cap)

    covered_rows = sum(
        1 for r in rows
        if r["brd"] == COMPLETE and r["prd"] == COMPLETE and r["user_story"] == COMPLETE
        and r["ux"] in (COMPLETE, NOT_APPLICABLE)
        and r["technical"] in (COMPLETE, NOT_APPLICABLE)
        and r["security"] in (COMPLETE, NOT_APPLICABLE)
    )
    coverage_pct = round(100 * covered_rows / len(rows)) if rows else 0
    if unmapped_idea_capabilities and rows:
        # An idea-implied capability with literally no module can't be
        # reflected in the row-based percentage above (there's no row for
        # it) — penalize the reported percentage so it can't read 100%
        # while something real is still missing outright.
        coverage_pct = min(coverage_pct, round(100 * covered_rows / (len(rows) + len(unmapped_idea_capabilities))))

    totals = {
        "capabilities": len(rows),
        "business_requirements": len(requirements),
        "prd_features": len(prd_fr_ids),
        "user_stories": len(stories),
        "ux_screens": len(screens),
        "ux_flows": len(flows),
        "coverage_percentage": coverage_pct,
    }

    return {
        "rows": rows,
        "totals": totals,
        "missing_capabilities": missing_capabilities,
        "partial_capabilities": partial_capabilities,
        "unmapped_idea_capabilities": unmapped_idea_capabilities,
    }


def matrix_has_blocking_gaps(matrix: dict) -> bool:
    return bool(
        matrix.get("missing_capabilities")
        or matrix.get("partial_capabilities")
        or matrix.get("unmapped_idea_capabilities")
    )


def gap_resolution_notes(matrix: dict) -> list[str]:
    """Turns the coverage matrix's gaps into concrete, per-capability
    resolution-note strings the content agents can act on directly (see
    BaseAgent.resolution_notes_block) — specific enough to fix without
    asking the user anything, since everything needed to fix them is
    already derivable from the business idea and discovery answers."""
    notes = []
    for row in matrix["rows"]:
        problems = []
        if row["brd"] == MISSING:
            problems.append("has no Business Requirement at all")
        if row["prd"] in _BLOCKING:
            problems.append(f"is {row['prd']} in the PRD's functional requirements (every FR id from the BRD must be reused, not dropped or renumbered)")
        if row["user_story"] in _BLOCKING:
            problems.append(f"is {row['user_story']} in the User Stories (every FR id needs at least one story via related_fr_ids)")
        if row["ux"] in _BLOCKING:
            problems.append(f"is {row['ux']} in the UX/Product Flow screens or flows (every FR id needs a screen or flow via related_requirement_ids)")
        if row["technical"] == MISSING:
            problems.append("has no corresponding Technical Requirement in the PRD's technical_integration_constraints/non_functional_requirements")
        if row["security"] == MISSING:
            problems.append("has no corresponding Security Requirement in the PRD's security_privacy_access_constraints")
        if problems:
            notes.append(
                f"Capability \"{row['capability']}\" ({', '.join(row['fr_ids']) or 'no FR IDs yet'}): "
                + "; ".join(problems)
                + ". Fix this directly from the business idea and discovery answers — do not ask the user for more information first."
            )
    for cap in matrix.get("unmapped_idea_capabilities", []):
        notes.append(
            f"The business idea and/or discovery answers clearly imply the capability \"{cap}\", but no module or "
            f"functional requirement for it exists in the Business Requirements at all. Add a dedicated module with "
            f"its own functional requirement(s) for it, and carry those requirements through the User Stories, PRD, "
            f"and UX/Product Flow — unless it is genuinely out of scope for this product, in which case say so "
            f"explicitly in scope_out with a documented reason rather than silently omitting it."
        )
    return notes

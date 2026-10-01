"""
Feasibility & Competitive Assessment Agent -> Feasibility & Competitive Assessment document
Answers: "Will this idea work — who else does it, what makes it different, and what is wrong with it?"

Runs FIRST, right after discovery, before the specification agents. Reasons for that placement:
  * It can change the idea. Finding a critical flaw after five agents have written 500 pages is expensive.
  * It is deliberately independent of the agents that write the requirements: an author should not
    grade its own idea. It never sees (or edits) the BRD/PRD; the specification agents read ITS findings.
  * It is advisory. It is not part of the Design-AI handoff, and the automatic gap-correction loop
    never re-runs it.

Output verdict is exactly one of:  GO  /  GO WITH CHANGES  /  RETHINK
The verdict is computed in code from the severity of the flaws and the ratings, so an optimistic
model reply cannot turn a critical flaw into a "GO"; the model's own opinion can only make it
more cautious (and RETHINK requires at least one critical flaw to back it).

Evidence honesty:
  * MOCK mode never invents competitor names. It lists competitor CATEGORIES and says so.
  * LIVE mode names real competitors from the model's training knowledge; the document states that
    this is not verified against live sources.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import BaseAgent  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402
import chunked as ch  # noqa: E402
import content_kit as ck  # noqa: E402
import system_profile as sp  # noqa: E402

VERDICTS = ("GO", "GO WITH CHANGES", "RETHINK")
RATINGS = ("High", "Medium", "Low")
SEVERITIES = ("Critical", "Major", "Minor")
DIMENSIONS = [
    ("desirability", "Desirability — will people want and use it?"),
    ("technical", "Technical feasibility — can it be built and run as described?"),
    ("operational", "Operational feasibility — can it be run day to day?"),
    ("financial", "Financial viability — can it make money?"),
    ("legal", "Legal & regulatory feasibility — is it allowed, and at what cost?"),
]

EVIDENCE_LIVE = ("Market, competitor and pricing information in this document was produced by an AI model from its training "
                 "knowledge. It has NOT been verified against live sources, and products, prices and market conditions change. "
                 "Verify every competitor name, claim and figure before relying on it in an investment or build decision.")
EVIDENCE_MOCK = ("This assessment was produced in demonstration (mock) mode. Competitors are listed as CATEGORIES, not by name, "
                 "because no AI model was available to identify real products; flaws come from rule-based checks on your discovery "
                 "answers. Run with an AI model key for named competitors and a deeper analysis.")


# --------------------------------------------------------------------------------------------
# Shared finishing step: ids, verdict, counts (used by mock and live)
# --------------------------------------------------------------------------------------------
def _norm_choice(value, allowed, default):
    v = str(value or "").strip().lower()
    for a in allowed:
        if v == a.lower():
            return a
    return default


def finalize(out: dict, llm_verdict: str | None = None) -> dict:
    flaws = out.get("flaws") or []
    for i, f in enumerate(flaws, start=1):
        f["id"] = f"FLAW-{i:02d}"
        f["severity"] = _norm_choice(f.get("severity"), SEVERITIES, "Major")
    order = {s: i for i, s in enumerate(SEVERITIES)}
    flaws.sort(key=lambda f: order[f["severity"]])
    for i, f in enumerate(flaws, start=1):          # renumber after sorting so IDs read top-down
        f["id"] = f"FLAW-{i:02d}"
    out["flaws"] = flaws

    dims = out.get("feasibility") or {}
    for key, _label in DIMENSIONS:
        d = dims.get(key) or {}
        dims[key] = {"rating": _norm_choice(d.get("rating"), RATINGS, "Medium"), "assessment": str(d.get("assessment") or "Not assessed.")}
    out["feasibility"] = dims

    critical = sum(1 for f in flaws if f["severity"] == "Critical")
    major = sum(1 for f in flaws if f["severity"] == "Major")
    low = sum(1 for d in dims.values() if d["rating"] == "Low")

    if critical >= 2 or (critical >= 1 and low >= 2):
        computed = "RETHINK"
    elif critical == 1 or major >= 2 or low >= 1:
        computed = "GO WITH CHANGES"
    else:
        computed = "GO"
    stated = _norm_choice(llm_verdict, VERDICTS, computed)
    # the model may only make the verdict MORE cautious, and cannot reach RETHINK without a critical flaw
    rank = {v: i for i, v in enumerate(VERDICTS)}
    verdict = stated if rank[stated] > rank[computed] else computed
    if verdict == "RETHINK" and critical == 0:
        verdict = "GO WITH CHANGES"
    out["verdict"] = verdict
    out["counts"] = {"critical": critical, "major": major, "minor": len(flaws) - critical - major,
                     "competitors": len(out.get("competitors") or []), "differentiators": len(out.get("differentiators") or [])}
    out["headline_flaws"] = [f["flaw"] for f in flaws if f["severity"] in ("Critical", "Major")][:5]
    out["summary"] = (f"Feasibility verdict: {verdict} — {critical} critical and {major} major flaw(s), "
                      f"{len(out.get('competitors') or [])} competitor(s)/categories and {len(out.get('differentiators') or [])} differentiator(s) assessed.")
    out.setdefault("confidence", "Medium")
    return out


# --------------------------------------------------------------------------------------------
# MOCK generator — rule-based, honest about its limits
# --------------------------------------------------------------------------------------------
def _by_category(context: ProjectContext, *needles: str) -> str:
    for q in context.discovery_questions:
        if q.answer and any(n in f"{q.category} {q.text}".lower() for n in needles):
            return q.answer
    return ""


def _mock(context: ProjectContext) -> dict:
    profile = sp.ensure_profile(context)
    planning = profile["scale"]["planning"]
    vocab = ck.get_vocab(context.domain_classification)
    domain = ck.domain_readable(context)
    idea = context.business_idea_raw
    text = " ".join(q.answer or "" for q in context.discovery_questions).lower() + " " + idea.lower()   # answers only, not question wording
    answered = [q for q in context.discovery_questions if q.answer and q.id != "additional_information"]
    unsure = [q for q in context.discovery_questions
              if (q.answer and "not sure" in q.answer.lower()) or (q.answer and "not decided" in q.answer.lower())
              or (q.answer and "haven't decided" in q.answer.lower()) or q.status.value == "skipped"]
    two_sided = context.domain_classification in ("booking_platform", "marketplace") or any(
        k in text for k in ("marketplace", "connect", "two-sided", "providers and", "sellers and", "vendors"))
    has_payments = any(k in text for k in ("payment", "commission", "checkout", "subscription"))
    competition = _by_category(context, "compet", "alternative")
    differentiation = _by_category(context, "differentiat", "value_proposition", "unique", "vision")
    team = _by_category(context, "team", "resourc", "budget")
    timeline = _by_category(context, "timeline", "launch date", "when do you")
    monetisation = _by_category(context, "monetiz", "revenue", "business_model", "make money", "pricing")
    modules = ck.select_modules(context)
    sens_label = _by_category(context, "sensitive data").lower()

    # ---------------- competitors (categories only) ----------------
    threat_direct = "High" if "few direct" in competition.lower() or "direct competitors" in competition.lower() else "Medium"
    competitors = [
        {"name": f"Established platforms and apps in the {domain} space", "type": "Direct",
         "what_they_do": f"Already connect {vocab['buyer'].lower()}s with {vocab['seller'].lower()}s / {vocab['item'].lower()}s and have existing users and supply.",
         "strengths": "Brand awareness, existing user base, established supply, marketing budget.",
         "weaknesses": "Often generic, slow to change, fee-heavy or weak on a specific niche or experience.",
         "pricing_model": "Not researched (mock mode).", "threat_level": threat_direct},
        {"name": "General-purpose marketplaces, classifieds and social groups", "type": "Indirect",
         "what_they_do": f"Let people find and arrange a {vocab['transaction'].lower()} informally without a dedicated product.",
         "strengths": "Free or cheap, huge reach, no sign-up friction.",
         "weaknesses": "No quality control, no payment protection, no structured workflow, high effort per transaction.",
         "pricing_model": "Not researched (mock mode).", "threat_level": "Medium"},
        {"name": "Manual and offline alternatives", "type": "Substitute",
         "what_they_do": "Phone calls, messaging apps, spreadsheets, word of mouth and personal contacts.",
         "strengths": "Zero cost to adopt, personal trust, no new habit required.",
         "weaknesses": "Slow, error-prone, does not scale, no transparency or record.",
         "pricing_model": "Free / time cost.", "threat_level": "Medium"},
    ]

    # ---------------- differentiators ----------------
    diffs = []
    if differentiation:
        diffs.append({"differentiator": "Founder-stated value proposition", "description": differentiation[:400],
                      "competitors_lacking": "Not assessed (mock mode cannot name competitors).", "defensibility": "Moderate",
                      "risk_if_copied": "Depends on how easily an incumbent can copy it; validate with target users."})
    trust = _by_category(context, "trust", "safety", "verif")
    if trust:
        diffs.append({"differentiator": "Trust and quality assurance", "description": f"Built-in trust mechanisms ({trust[:160]}).",
                      "competitors_lacking": "General-purpose channels and informal alternatives.", "defensibility": "Moderate",
                      "risk_if_copied": "Incumbents can add verification, but it costs them operations to do well."})
    if any(k in text for k in (" ai ", "ai-powered", "ai powered", "ai-assisted", "recommend", "machine learning")):
        diffs.append({"differentiator": "AI-assisted experience", "description": "AI features that reduce effort (recommendations, matching, automation).",
                      "competitors_lacking": "Manual and general-purpose alternatives.", "defensibility": "Weak",
                      "risk_if_copied": "AI capabilities are widely available; the moat is the data and workflow, not the model."})
    if two_sided:
        diffs.append({"differentiator": "Structured, end-to-end workflow", "description": f"One place to discover, commit to, pay for and review a {vocab['transaction'].lower()}.",
                      "competitors_lacking": "Manual and informal alternatives.", "defensibility": "Weak",
                      "risk_if_copied": "The workflow itself is easy to copy; network density is what protects it."})
    positioning = (f"For {ck.target_users_phrase(context).lower()} who need a better way to complete a {vocab['transaction'].lower()}, "
                   f"this {domain} product offers a structured, transparent alternative to manual and generic options. "
                   + ("Its stated differentiation is: " + differentiation[:200] if differentiation
                      else "A specific differentiator has NOT yet been stated and must be defined."))

    # ---------------- flaws ----------------
    flaws: list[dict] = []

    def flaw(sev, area, what, why, fix):
        flaws.append({"severity": sev, "area": area, "flaw": what, "why_it_matters": why, "recommended_change": fix})

    if not differentiation:
        flaw("Major", "Differentiation", "No clear reason for users to choose this product over existing options has been stated.",
             "Without a sharp differentiator the product competes on price and marketing spend, which favours incumbents.",
             "Define one specific thing this product does better for one specific user group, and test it with 10+ target users before building.")
    if "no real competitors" in competition.lower():
        flaw("Major", "Market evidence", "The idea assumes there are no real competitors.",
             "Either demand is unproven, or users are solving the problem another way (a substitute) that has not been recognised.",
             "List what users do today instead — including manual methods — and confirm they would switch and pay.")
    if two_sided:
        flaw("Major", "Cold start", f"The product needs {vocab['buyer'].lower()}s and {vocab['seller'].lower()}s at the same time; each side only joins if the other is already there.",
             "Two-sided products often fail before reaching the density that makes them useful.",
             f"Launch in one narrow area or niche, secure the {vocab['seller'].lower()} side first (manually if needed), and set a target for supply density before opening to {vocab['buyer'].lower()}s.")
        if has_payments:
            flaw("Major", "Business model", "Users may complete repeat transactions off the platform to avoid fees (disintermediation).",
                 "If the revenue depends on a commission or fee per transaction, leakage directly cuts revenue.",
                 "Give both sides ongoing reasons to stay (payment protection, guarantees, scheduling, reviews, insurance) and consider subscription or lead-fee models.")
    if monetisation and any(w in monetisation.lower() for w in ("not decided", "haven't", "not sure")):
        flaw("Major", "Business model", "How the product will make money has not been decided.",
             "Unit economics drive almost every design and scope decision; leaving them open risks building a product that cannot pay for itself.",
             "Choose a provisional revenue model and check it with a simple estimate: revenue per user versus acquisition and running cost.")
    if len(answered) and len(unsure) / max(1, len(answered) + len(unsure)) >= 0.25:
        flaw("Major", "Undecided fundamentals", f"{len(unsure)} discovery questions were skipped or answered 'not sure'.",
             "Many open decisions mean the specification will contain assumptions that may not hold.",
             "Resolve the open questions in the questionnaire (use Edit on the review screen) before relying on the specification.")
    users = planning["users_12m"]
    if users >= 50_000 and any(w in team.lower() for w in ("solo", "small team")):
        flaw("Critical", "Scope vs resources", f"The plan targets up to {users:,} users in year one, but the team is described as '{team}'.",
             "Building, securing, running and supporting a product at this scale usually needs a larger team or a much narrower first release.",
             "Cut the first release to the smallest useful scope, plan for hundreds of users before thousands, or secure funding/partners for a larger team.")
    if timeline and "within 3 months" in timeline.lower() and len(modules) >= 20:
        flaw("Major", "Scope vs timeline", f"A launch within 3 months is planned, but the product spans {len(modules)} functional modules.",
             "The scope is unlikely to fit the timeline, which leads to rushed quality or missed launch.",
             "Choose the 5-8 modules needed for a first usable release (the MVP tiers in the BRD show a starting point) and defer the rest.")
    sensitive = [k for k, w in (("health", "health"), ("children", "children"), ("identity documents", "identity"), ("payment", "payment")) if w in sens_label]
    if sensitive:
        flaw("Major", "Regulatory", f"The product handles sensitive data ({', '.join(sensitive)}).",
             "Sensitive data brings legal duties, audits and breach liability that increase cost and delay launch.",
             "Get legal advice on the rules for the launch geography before build; minimise stored data and use specialist providers (for example a hosted payment provider).")
    if any(k in text for k in (" ai ", "ai-powered", "recommend", "machine learning", "chatbot")):
        flaw("Minor", "AI dependence", "Part of the value depends on AI output quality.",
             "Poor or inconsistent AI results damage trust quickly; ongoing model cost also scales with usage.",
             "Define a quality bar, a non-AI fallback and a per-user cost limit before committing to AI features.")
    flaw("Minor", "Demand evidence", "There is no evidence in the discovery answers that target users have been asked whether they would use and pay for this.",
         "The specification assumes demand; if it is wrong, every later investment is at risk.",
         "Interview 10-20 target users, or run a simple landing page / manual pilot, before committing to the full build.")

    # ---------------- feasibility dimensions ----------------
    n_modules = len(modules)
    critical_scope = any(f["severity"] == "Critical" for f in flaws)
    dims = {
        "desirability": {
            "rating": "Low" if any(f["area"] in ("Differentiation", "Market evidence") for f in flaws) and not diffs else "Medium",
            "assessment": ("The problem is plausible, but demand and differentiation are not evidenced in the answers. "
                           "See the flaws on differentiation and demand evidence.")},
        "technical": {
            "rating": "Low" if (users >= 500_000 and critical_scope) else "Medium" if (n_modules >= 20 or users >= 50_000) else "High",
            "assessment": (f"About {n_modules} functional modules are implied. Planning volume is up to {users:,} users "
                           f"({planning['peak']:,} concurrent). This is standard web/mobile architecture; effort and complexity grow with module count and load.")},
        "operational": {
            "rating": "Low" if critical_scope else "Medium",
            "assessment": ("Running the product day to day needs support, moderation/dispute handling and "
                           + (f"{vocab['seller'].lower()} onboarding and quality control. " if two_sided else "content/data upkeep. ")
                           + f"Team described as: {team or 'not stated'}.")},
        "financial": {
            "rating": "Low" if any(f["area"] == "Business model" and "not been decided" in f["flaw"] for f in flaws) else "Medium",
            "assessment": ("Revenue model: " + (monetisation or "not stated") + ". No cost or revenue estimate exists in the answers, so viability is unproven.")},
        "legal": {
            "rating": "Low" if any(k in sens_label for k in ("health", "children")) else "Medium" if sensitive else "High",
            "assessment": ("Data handled: " + (sens_label or "not stated") + ". Applicable regulation depends on the launch geography and must be confirmed.")},
    }

    assumptions = [
        {"assumption": f"{vocab['buyer']}s will switch from their current method to this product.",
         "how_to_validate": "Interview 10-20 target users about how they do this today and what would make them switch.",
         "risk_if_wrong": "Low adoption; the product is built but not used."},
        {"assumption": "The revenue model works at realistic volumes.", "how_to_validate": "Model revenue per user against acquisition, payment, hosting and support cost.",
         "risk_if_wrong": "The product cannot pay for itself."},
        {"assumption": f"Enough {vocab['seller'].lower()}s / supply will join." if two_sided else "The data or content the product needs will be available.",
         "how_to_validate": "Pre-sign a small first group before build; measure how many say yes.", "risk_if_wrong": "Empty product at launch."},
        {"assumption": f"Planning volume of up to {users:,} users in the first 12 months is realistic.",
         "how_to_validate": "Compare with the marketing plan and channel size; check comparable products.", "risk_if_wrong": "Over- or under-building the platform."},
    ]
    changes = [f["recommended_change"] for f in flaws if f["severity"] in ("Critical", "Major")][:8]
    if not changes:
        changes = ["No blocking changes identified. Validate the assumptions below with real users before the full build."]

    out = {
        "idea_summary": idea,
        "verdict_rationale": "",
        "confidence": "Low",
        "evidence_note": EVIDENCE_MOCK,
        "target_market": f"{ck.target_users_phrase(context)} in the {domain} space.",
        "demand_signals": ["No external demand data was gathered in mock mode.",
                           "The founder's discovery answers describe a real workflow problem."],
        "market_risks": ["Incumbents can copy visible features.", "Adoption depends on changing an existing habit."],
        "competitors": competitors,
        "competitive_gaps": ["A specific gap versus named competitors could not be assessed in mock mode."],
        "differentiators": diffs,
        "positioning_statement": positioning,
        "feasibility": dims,
        "flaws": flaws,
        "assumptions_to_validate": assumptions,
        "recommended_changes": changes,
        "must_confirm_before_build": profile["open_questions"][:6],
    }
    out = finalize(out)
    out["verdict_rationale"] = _rationale(out)
    return out


def _rationale(out: dict) -> str:
    c = out["counts"]
    v = out["verdict"]
    if v == "RETHINK":
        head = "The idea should be reworked before any specification effort is spent on it."
    elif v == "GO WITH CHANGES":
        head = "The idea is workable, but the issues below should be addressed first or the specification will inherit them."
    else:
        head = "No blocking issues were found. Proceed, and validate the assumptions with real users."
    lows = [k for k, d in out["feasibility"].items() if d["rating"] == "Low"]
    tail = f" {c['critical']} critical and {c['major']} major flaw(s) were found." if (c["critical"] or c["major"]) else ""
    if lows:
        tail += " Weakest dimension(s): " + ", ".join(lows) + "."
    return head + tail


# --------------------------------------------------------------------------------------------
# LIVE generator — two focused calls (market & competition, then feasibility & flaws)
# --------------------------------------------------------------------------------------------
def _live_market_prompt(context: ProjectContext) -> str:
    return (
        ch.tag("feasibility.market") +
        "You are an experienced product strategist and market analyst. Analyse the competitive landscape for this business idea "
        "and identify what could make it different.\n\n" + _plain_idea(context) +
        "\nRules:\n"
        "- Name only REAL competitors and products you are confident exist and that operate in the market the answers describe "
        "(pay attention to the launch geography if given). If you are not sure a specific product exists, describe the CATEGORY instead. "
        "Never invent a company, a price, a user count or a statistic. If you do not know, write 'Unknown'.\n"
        "- Include direct competitors, indirect competitors, and the manual/offline substitute people use today. 6-10 entries.\n"
        "- Be honest and critical about differentiators: a differentiator is only real if competitors lack it AND it would be hard to copy. "
        "Rate defensibility Strong, Moderate or Weak. If the answers state no differentiator, propose the most plausible ones and say they are proposals.\n\n"
        'Respond ONLY with JSON:\n{"idea_summary": "one sentence", "target_market": "who and where", '
        '"demand_signals": ["evidence that demand exists"], "market_risks": ["..."], '
        '"competitors": [{"name": "...", "type": "Direct|Indirect|Substitute", "what_they_do": "...", "strengths": "...", "weaknesses": "...", '
        '"pricing_model": "... or Unknown", "threat_level": "High|Medium|Low"}], '
        '"competitive_gaps": ["unmet needs / weaknesses across competitors"], '
        '"differentiators": [{"differentiator": "...", "description": "...", "competitors_lacking": "...", "defensibility": "Strong|Moderate|Weak", "risk_if_copied": "..."}], '
        '"positioning_statement": "For [target] who [need], [product] is a [category] that [key benefit]. Unlike [alternatives], it [difference]."}'
    )


def _live_feasibility_prompt(context: ProjectContext, market: dict, profile: dict) -> str:
    comp = "; ".join(f"{c.get('name')} ({c.get('type')}, threat {c.get('threat_level')})" for c in market.get("competitors", []))
    diffs = "; ".join(f"{d.get('differentiator')} [{d.get('defensibility')}]" for d in market.get("differentiators", []))
    scale = "\n".join(f"- {r['parameter']}: {r['value']} [{r['basis']}]" for r in profile["scale"]["rows"])
    return (
        ch.tag("feasibility.assess") +
        "You are a sceptical, experienced startup advisor and solutions architect. Your job is to find out whether this idea will work "
        "and to find its flaws BEFORE money is spent building it. Be direct and specific. Do not flatter the idea. "
        "Do not invent statistics; reason from the answers given.\n\n" + _plain_idea(context) +
        f"\nCompetitive analysis already done: competitors — {comp or 'none'}; differentiators — {diffs or 'none identified'}.\n"
        f"Planning numbers (from the answers):\n{scale}\n\n"
        "Assess these five dimensions, each with a rating of High, Medium or Low (High = looks feasible) and a 2-4 sentence assessment "
        "grounded in the answers: desirability, technical, operational, financial, legal.\n"
        "Then list the flaws and weaknesses in the CURRENT idea (6-12), each with a severity: Critical = likely to make the product fail "
        "or be unbuildable as described; Major = seriously hurts the chance of success; Minor = worth fixing. Look especially for: "
        "unclear or unproven demand, weak or copyable differentiation, cold-start / network-effect problems, disintermediation, "
        "unit economics that do not work, scope that does not fit the team/timeline/budget, regulatory or data-protection exposure, "
        "dependence on a third party, contradictions between the answers, and answers left as 'not sure'.\n"
        "Then list the key assumptions that must be validated with real users/data (with how), the recommended changes to the idea "
        "(concrete, ordered by importance), and what must be confirmed before building. Give an overall verdict: GO, GO WITH CHANGES or RETHINK, "
        "with a 2-3 sentence rationale, and your confidence (High, Medium, Low).\n\n"
        'Respond ONLY with JSON:\n{"feasibility": {"desirability": {"rating": "High|Medium|Low", "assessment": "..."}, "technical": {...}, "operational": {...}, "financial": {...}, "legal": {...}}, '
        '"flaws": [{"severity": "Critical|Major|Minor", "area": "...", "flaw": "...", "why_it_matters": "...", "recommended_change": "..."}], '
        '"assumptions_to_validate": [{"assumption": "...", "how_to_validate": "...", "risk_if_wrong": "..."}], '
        '"recommended_changes": ["..."], "must_confirm_before_build": ["..."], '
        '"verdict": "GO|GO WITH CHANGES|RETHINK", "verdict_rationale": "...", "confidence": "High|Medium|Low"}'
    )


def _plain_idea(context: ProjectContext) -> str:
    answered = "\n".join(f"- {q.text} -> {q.answer}" for q in context.discovery_questions if q.answer)
    skipped = "\n".join(f"- {q.text}" for q in context.discovery_questions if q.status.value == "skipped")
    return (f'Business idea: "{context.business_idea_raw}"\nDomain: {context.domain_classification}\n'
            f"Answered discovery questions:\n{answered or '- (none)'}\n" + (f"Questions the founder skipped:\n{skipped}\n" if skipped else ""))


def _list_of_dicts(raw, fields):
    out = []
    for it in raw or []:
        if isinstance(it, dict):
            out.append({f: str(it.get(f, "")).strip() for f in fields})
    return [o for o in out if o[fields[0]]]


def _live(context: ProjectContext, client) -> dict:
    profile = sp.ensure_profile(context, client)
    market = ch.call_json(client, _live_market_prompt(context), max_tokens=7000)
    assess = ch.call_json(client, _live_feasibility_prompt(context, market, profile), max_tokens=7000)

    competitors = _list_of_dicts(market.get("competitors"), ("name", "type", "what_they_do", "strengths", "weaknesses", "pricing_model", "threat_level"))
    for c in competitors:
        c["type"] = _norm_choice(c["type"], ("Direct", "Indirect", "Substitute"), "Direct")
        c["threat_level"] = _norm_choice(c["threat_level"], RATINGS, "Medium")
    diffs = _list_of_dicts(market.get("differentiators"), ("differentiator", "description", "competitors_lacking", "defensibility", "risk_if_copied"))
    for d in diffs:
        d["defensibility"] = _norm_choice(d["defensibility"], ("Strong", "Moderate", "Weak"), "Moderate")
    flaws = _list_of_dicts(assess.get("flaws"), ("severity", "area", "flaw", "why_it_matters", "recommended_change"))
    if not flaws:
        raise RuntimeError("the feasibility model returned no flaws — every idea has some; refusing to produce an empty assessment")

    def strs(v):
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    out = {
        "idea_summary": str(market.get("idea_summary") or context.business_idea_raw),
        "verdict_rationale": str(assess.get("verdict_rationale") or ""),
        "confidence": _norm_choice(assess.get("confidence"), RATINGS, "Medium"),
        "evidence_note": EVIDENCE_LIVE,
        "target_market": str(market.get("target_market") or ""),
        "demand_signals": strs(market.get("demand_signals")),
        "market_risks": strs(market.get("market_risks")),
        "competitors": competitors,
        "competitive_gaps": strs(market.get("competitive_gaps")),
        "differentiators": diffs,
        "positioning_statement": str(market.get("positioning_statement") or ""),
        "feasibility": assess.get("feasibility") or {},
        "flaws": flaws,
        "assumptions_to_validate": _list_of_dicts(assess.get("assumptions_to_validate"), ("assumption", "how_to_validate", "risk_if_wrong")),
        "recommended_changes": strs(assess.get("recommended_changes")),
        "must_confirm_before_build": strs(assess.get("must_confirm_before_build")) or profile["open_questions"][:6],
    }
    out = finalize(out, llm_verdict=assess.get("verdict"))
    if not out["verdict_rationale"]:
        out["verdict_rationale"] = _rationale(out)
    return out


# --------------------------------------------------------------------------------------------
class FeasibilityAssessmentAgent(BaseAgent):
    role = AgentRole.FEASIBILITY_ASSESSMENT
    max_output_tokens = 7000

    def build_prompt(self, context: ProjectContext) -> str:          # not used (live mode is multi-step)
        return _live_market_prompt(context)

    def generate_live(self, context: ProjectContext, client) -> dict:
        return _live(context, client)

    def mock_response(self, context: ProjectContext) -> dict:
        return _mock(context)


def findings_block(context: ProjectContext) -> str:
    """A compact block for the specification agents' prompts: the feasibility findings the documents
    must take into account (risks to mitigate, changes to the scope, differentiators to protect)."""
    c = context.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    if not c:
        return ""
    o = c.output
    lines = [f"FEASIBILITY FINDINGS (from an earlier independent assessment — verdict: {o.get('verdict')}). "
             "Reflect these in the risks, assumptions, scope decisions and goals where relevant; do not ignore them:"]
    for f in (o.get("flaws") or [])[:8]:
        if f.get("severity") in ("Critical", "Major"):
            lines.append(f"- [{f['severity']}] {f.get('flaw')} -> Mitigation: {f.get('recommended_change')}")
    diffs = [d.get("differentiator") for d in (o.get("differentiators") or []) if d.get("differentiator")]
    if diffs:
        lines.append("- Differentiators the product must clearly deliver: " + "; ".join(diffs[:5]))
    return "\n".join(lines) + "\n\n"

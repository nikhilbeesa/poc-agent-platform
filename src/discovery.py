"""
Discovery Engine
================
Turns a raw business idea into a classified domain plus a tailored set of
discovery questions. This is where AI reasoning is actually used (per the
guiding principle: AI for judgment calls, deterministic code for everything
else).

Two AI calls happen here:
1. classify_domain — decide which known domain (if any) this idea fits,
   or propose a new one.
2. generate_followup_questions — given the idea + seed questions, produce
   2-4 extra questions tailored to what THIS idea specifically needs.

Runs in two modes:
- LIVE mode: calls the real Claude API (requires ANTHROPIC_API_KEY env var)
- MOCK mode: used automatically when no API key is set, so this module
  can be developed/tested without API access. Mock logic uses simple
  keyword matching instead of the LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context import DiscoveryQuestion, ProjectContext, ProjectStage, QuestionStatus  # noqa: E402
from knowledge.bootstrap_seed_data import bootstrap  # noqa: E402
from knowledge.learn import learn_domain  # noqa: E402
from knowledge.store import get_knowledge_store  # noqa: E402
from llm_client import get_client  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()


# ---------------------------------------------------------------------------
# Step 1: Idea intake
# ---------------------------------------------------------------------------

def intake_idea(context: ProjectContext, idea_text: str) -> ProjectContext:
    """Deterministic — just records the raw idea and advances the stage."""
    context.business_idea_raw = idea_text.strip()
    context.stage = ProjectStage.DISCOVERY
    return context


# ---------------------------------------------------------------------------
# Step 2: Domain classification (AI reasoning)
# ---------------------------------------------------------------------------

def classify_domain(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "discovery_engine", "started",
                    {"step": "classify_domain"})

    store = bootstrap()  # ensures seed domains exist; no-op after first run
    known_names = store.list_domains()

    client = get_client()
    if client is None:
        domain, confidence = _mock_classify(context.business_idea_raw, known_names)
    else:
        domain, confidence = _live_classify(client, context.business_idea_raw, known_names)

    # If the classifier didn't land on a domain we already know, learn it
    # now — per spec Section 7: "unknown domains should be analysed and
    # incorporated without changing the platform architecture."
    if not store.domain_exists(domain):
        learned = learn_domain(context.business_idea_raw, domain, context.project_id, store)
        domain = learned["slug"]
        log_agent_call(logger, context.project_id, "discovery_engine", "info",
                        {"step": "classify_domain", "note": "learned new domain", "domain": domain})

    context.domain_classification = domain
    context.domain_confidence = confidence

    log_agent_call(logger, context.project_id, "discovery_engine", "completed",
                    {"step": "classify_domain", "domain": domain, "confidence": confidence})
    return context


def _live_classify(client, idea_text: str, known_names: list[str]) -> tuple[str, float]:
    known = ", ".join(known_names)
    prompt = f"""Classify this business idea into one of these known domains
if it clearly fits: {known}. If it doesn't fit any of them well, respond
with a short new domain name of your own (lowercase_with_underscores).

Business idea: "{idea_text}"

Respond ONLY with JSON, no other text:
{{"domain": "...", "confidence": 0.0}}"""

    text = client.generate(prompt, max_tokens=200)
    data = json.loads(text)
    return data["domain"], float(data["confidence"])


_STOPWORDS = {
    "a", "an", "the", "app", "apps", "platform", "tool", "that", "for",
    "people", "can", "and", "to", "of", "where", "who", "with", "their",
    "your", "you", "helps", "let", "lets", "allow", "allows", "connecting",
}


def _guess_domain_slug(idea_text: str) -> str:
    """Used only in mock mode as a stand-in for the LLM proposing a new
    domain name. Picks 1-2 meaningful words from the idea itself so
    different unrecognised ideas get different learned domains, rather
    than everything collapsing into one generic fallback."""
    words = [w.strip(".,!?").lower() for w in idea_text.split()]
    significant = [w for w in words if w not in _STOPWORDS and len(w) > 3]
    if len(significant) >= 2:
        return "_".join(significant[:2])
    if significant:
        return significant[0]
    return "general_business"


def _mock_classify(idea_text: str, known_names: list[str]) -> tuple[str, float]:
    """Simple keyword heuristic — stands in for the LLM call in mock mode."""
    text = idea_text.lower()
    if "booking_platform" in known_names and any(w in text for w in ["book", "appointment", "schedule", "reserve"]):
        return "booking_platform", 0.75
    if any(w in text for w in ["buy", "sell", "shop", "product", "store", "cart"]):
        if "marketplace" in known_names and any(w in text for w in ["connect", "seller", "vendor", "marketplace", "both sides"]):
            return "marketplace", 0.65
        if "e_commerce" in known_names:
            return "e_commerce", 0.75
    if "marketplace" in known_names and any(w in text for w in ["connect", "marketplace", "match", "peer to peer", "two-sided"]):
        return "marketplace", 0.7
    return _guess_domain_slug(idea_text), 0.3


# ---------------------------------------------------------------------------
# Step 3: Dynamic question generation (AI reasoning + seed knowledge)
# ---------------------------------------------------------------------------

def generate_discovery_questions(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "discovery_engine", "started",
                    {"step": "generate_questions"})

    store = get_knowledge_store()
    domain_info = store.get_domain(context.domain_classification)

    client = get_client()
    if client is None:
        # Mock/offline mode: same tested behavior as before — a fixed
        # per-domain checklist plus 2 generic mock follow-ups. This is
        # intentionally NOT dynamic, because there's no real reasoning
        # available to generate genuinely tailored questions offline.
        questions: list[DiscoveryQuestion] = []
        if domain_info:
            for q in domain_info["seed_questions"]:
                questions.append(DiscoveryQuestion(**q))
        questions.extend(_mock_followups(context))
    else:
        # Live mode: the FULL question set is generated fresh for this
        # specific idea. The domain's description/typical_modules are
        # passed as light context — not a verbatim checklist — so two
        # different ideas in the same domain (e.g. two different booking
        # apps) get genuinely different questions, not the same fixed
        # list every time. This is what makes discovery actually dynamic
        # rather than a templated form with the domain name swapped in.
        questions = _live_dynamic_questions(client, context, domain_info)

    context.discovery_questions = questions

    log_agent_call(logger, context.project_id, "discovery_engine", "completed",
                    {"step": "generate_questions", "count": len(questions),
                     "mode": "mock" if client is None else "live_dynamic"})
    return context


def _live_dynamic_questions(client, context: ProjectContext, domain_info: dict | None) -> list[DiscoveryQuestion]:
    if domain_info:
        context_note = (
            f"Domain: {context.domain_classification} — {domain_info['description']}\n"
            f"Businesses like this typically need: {', '.join(domain_info.get('typical_modules', []))}"
        )
    else:
        context_note = f"Domain: {context.domain_classification} (a newly-identified, unfamiliar business type)"

    prompt = f"""Business idea: "{context.business_idea_raw}"
{context_note}

Generate ALL the discovery questions you genuinely need to fully
understand this business idea before a team could start building it —
don't stop at an arbitrary count. A simple idea might only need 5-6
questions; a complex one might genuinely need 15-20+. Use your judgment
on how many are actually necessary, not a fixed number.

Make sure you've covered, wherever relevant to this specific idea:
- target users / customer segments
- core operations and day-to-day workflow
- monetization, pricing, and payments
- technical or platform requirements
- competition and differentiation
- legal, compliance, or regulatory considerations
- growth and scaling plans
- risks or unknowns specific to this idea
- anything unique to THIS idea that a generic template for the domain would miss

Questions must be SPECIFIC to this exact idea, not generic boilerplate.
Two different ideas in the same domain should get noticeably different
questions. Don't ask questions whose answer is already obvious from the
idea as stated.

Respond ONLY with JSON, no other text:
{{"questions": [{{"id": "short_id", "text": "...", "category": "..."}}]}}"""

    text = client.generate(prompt, max_tokens=3000)
    data = json.loads(text)
    return [DiscoveryQuestion(**q) for q in data["questions"]]


def _mock_followups(context: ProjectContext) -> list[DiscoveryQuestion]:
    """Stands in for the LLM's tailored follow-ups in mock mode."""
    return [
        DiscoveryQuestion(
            id="mock_scale",
            text="Roughly how many users do you expect in the first 6 months?",
            category="scale",
        ),
        DiscoveryQuestion(
            id="mock_platform",
            text="Web, mobile app, or both?",
            category="platform",
        ),
    ]


# ---------------------------------------------------------------------------
# Helpers for driving the questionnaire
# ---------------------------------------------------------------------------

def next_pending_question(context: ProjectContext) -> DiscoveryQuestion | None:
    for q in context.discovery_questions:
        if q.status == QuestionStatus.PENDING:
            return q
    return None


def is_discovery_complete(context: ProjectContext) -> bool:
    return all(q.status != QuestionStatus.PENDING for q in context.discovery_questions)


def run_discovery(context: ProjectContext, idea_text: str) -> ProjectContext:
    """Full Phase 2 pipeline: intake -> classify -> generate questions."""
    context = intake_idea(context, idea_text)
    context = classify_domain(context)
    context = generate_discovery_questions(context)
    return context


if __name__ == "__main__":
    ctx = ProjectContext()
    ctx = run_discovery(ctx, "An app where people can book home cleaners for one-off or recurring visits")

    print(f"\nDomain classified as: {ctx.domain_classification} (confidence: {ctx.domain_confidence})")
    print(f"\nGenerated {len(ctx.discovery_questions)} discovery questions:\n")
    for q in ctx.discovery_questions:
        print(f"  [{q.category}] {q.text}")

    # Simulate answering a couple of questions
    if ctx.discovery_questions:
        ctx.add_answer(ctx.discovery_questions[0].id, "Individual homeowners, mostly recurring bookings")
        print(f"\nAnswered: '{ctx.discovery_questions[0].text}' -> '{ctx.discovery_questions[0].answer}'")

    print(f"\nDiscovery complete: {is_discovery_complete(ctx)}")
    ctx.save("/tmp/discovery_test_context.json")
    print("Saved test context to /tmp/discovery_test_context.json")

from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import DiscoveryQuestion, ProjectContext, ProjectStage, QuestionStatus  # noqa: E402
from knowledge.bootstrap_seed_data import bootstrap  # noqa: E402
from knowledge.learn import learn_domain  # noqa: E402
from knowledge.store import get_knowledge_store  # noqa: E402
from llm_client import get_client  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()


def intake_idea(context: ProjectContext, idea_text: str) -> ProjectContext:
    context.business_idea_raw = idea_text.strip()
    context.stage = ProjectStage.DISCOVERY
    return context


def classify_domain(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "discovery_engine", "started", {"step": "classify_domain"})
    store = bootstrap()
    known_names = store.list_domains()
    client = get_client()
    if client is None:
        domain, confidence = _mock_classify(context.business_idea_raw, known_names)
    else:
        domain, confidence = _live_classify(client, context.business_idea_raw, known_names)
    if not store.domain_exists(domain):
        learned = learn_domain(context.business_idea_raw, domain, context.project_id, store)
        domain = learned["slug"]
    context.domain_classification = domain
    context.domain_confidence = confidence
    log_agent_call(logger, context.project_id, "discovery_engine", "completed", {"step": "classify_domain", "domain": domain, "confidence": confidence})
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


_STOPWORDS = {"a", "an", "the", "app", "apps", "platform", "tool", "that", "for", "people", "can", "and", "to", "of", "where", "who", "with", "their", "your", "you", "helps", "let", "lets", "allow", "allows", "connecting"}


def _guess_domain_slug(idea_text: str) -> str:
    words = [w.strip(".,!?").lower() for w in idea_text.split()]
    significant = [w for w in words if w not in _STOPWORDS and len(w) > 3]
    if len(significant) >= 2:
        return "_".join(significant[:2])
    if significant:
        return significant[0]
    return "general_business"


def _mock_classify(idea_text: str, known_names: list[str]) -> tuple[str, float]:
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


def generate_discovery_questions(context: ProjectContext) -> ProjectContext:
    log_agent_call(logger, context.project_id, "discovery_engine", "started", {"step": "generate_questions"})
    store = get_knowledge_store()
    domain_info = store.get_domain(context.domain_classification)
    client = get_client()
    if client is None:
        questions: list[DiscoveryQuestion] = []
        if domain_info:
            for q in domain_info["seed_questions"]:
                questions.append(DiscoveryQuestion(**q))
        questions.extend(_mock_followups(context))
    else:
        questions = _live_dynamic_questions(client, context, domain_info)
    for q in questions:
        if not q.options:
            q.options = _infer_options(q.category, q.text)
    context.discovery_questions = questions
    log_agent_call(logger, context.project_id, "discovery_engine", "completed", {"step": "generate_questions", "count": len(questions)})
    return context


# Fallback heuristic used whenever a question (mock or LLM-generated) doesn't
# already carry its own options, so choice-based UI degrades gracefully
# instead of falling back to a free-text box more often than necessary.
_OPTION_BANK: list[tuple[tuple[str, ...], list[str]]] = [
    (("user", "audience", "customer"), ["Individual consumers", "Small businesses", "Enterprise teams", "Multiple user types"]),
    (("payment", "pricing", "monetiz", "revenue", "business_model"), ["Commission on transactions", "Subscription fees", "One-time/listing fees", "Not decided yet"]),
    (("cancel", "refund", "policy", "return"), ["Flexible — full refunds", "Strict — limited or no refunds", "Case-by-case", "Haven't decided yet"]),
    (("trust", "safety", "verif", "fraud"), ["Verified profiles / ID checks", "Ratings & reviews", "Secure/escrow payments", "Not sure yet"]),
    (("discover", "search", "match", "recommend"), ["Search & filters", "Algorithmic recommendations", "Browsing categories", "A mix of these"]),
    (("scale", "volume", "how many"), ["Under 100", "100–1,000", "1,000–10,000", "10,000+"]),
    (("platform", "web", "mobile", "device"), ["Web app", "Mobile app", "Both web & mobile", "Not sure yet"]),
    (("catalog", "inventory", "product count"), ["Fewer than 50", "50–500", "500+", "Not sure yet"]),
    (("fulfil", "shipping", "logistics", "deliver"), ["We handle it ourselves", "A third-party partner", "Dropshipping", "Not decided yet"]),
    (("schedul", "availab"), ["Set by each provider", "Assigned centrally", "A mix of both", "Not sure yet"]),
    (("onboard", "vett", "signup"), ["Open self-signup", "Self-signup with review", "Fully vetted/curated", "Not decided yet"]),
    (("compet", "alternative"), ["Yes, a few direct competitors", "Only indirect alternatives", "No real competitors yet", "Not sure yet"]),
    (("legal", "complian", "regulat", "privacy"), ["Standard consumer terms/privacy", "Industry-specific regulation applies", "Not sure yet", "Need legal review"]),
    (("team", "resourc", "budget"), ["Solo founder", "Small team (2–5)", "Funded team (6+)", "Not sure yet"]),
    (("timeline", "launch", "when"), ["Within 3 months", "3–6 months", "6–12 months", "No fixed timeline"]),
]


_FREE_TEXT_CATEGORIES = {"value_proposition", "differentiation", "vision", "risks", "naming"}


def _infer_options(category: str, text: str) -> list[str]:
    if category.lower() in _FREE_TEXT_CATEGORIES:
        return []
    haystack = f"{category} {text}".lower()
    for keywords, options in _OPTION_BANK:
        if any(k in haystack for k in keywords):
            return options
    return []


def _live_dynamic_questions(client, context: ProjectContext, domain_info: dict | None) -> list[DiscoveryQuestion]:
    if domain_info:
        context_note = f"Domain: {context.domain_classification} — {domain_info['description']}\nBusinesses like this typically need: {', '.join(domain_info.get('typical_modules', []))}"
    else:
        context_note = f"Domain: {context.domain_classification} (a newly-identified, unfamiliar business type)"

    prompt = f"""Business idea: "{context.business_idea_raw}"
{context_note}

Generate ALL the discovery questions you genuinely need to fully
understand this business idea before a team could start building it —
don't stop at an arbitrary count. A simple idea might only need 5-6
questions; a complex one might genuinely need 15-20+.

Cover, wherever relevant: target users/segments, core operations,
monetization/pricing, technical/platform requirements, competition,
legal/compliance, growth plans, risks, and anything unique to THIS idea.

For each question, also propose 3-6 short tappable answer options (a few
words each) whenever the question naturally has a small set of likely
answers — this lets the user tap instead of type. If a question genuinely
needs a free-text or numeric answer (e.g. a specific name, a precise
number), give it an empty options array instead of forcing choices.

Respond ONLY with JSON, no other text:
{{"questions": [{{"id": "short_id", "text": "...", "category": "...", "options": ["..."]}}]}}"""
    text = client.generate(prompt, max_tokens=4000)
    data = json.loads(text)
    return [DiscoveryQuestion(**q) for q in data["questions"]]


def _mock_followups(context: ProjectContext) -> list[DiscoveryQuestion]:
    return [
        DiscoveryQuestion(
            id="mock_scale", text="Roughly how many users do you expect in the first 6 months?", category="scale",
            options=["Under 100", "100–1,000", "1,000–10,000", "10,000+"],
        ),
        DiscoveryQuestion(
            id="mock_platform", text="Web, mobile app, or both?", category="platform",
            options=["Web app", "Mobile app", "Both web & mobile", "Not sure yet"],
        ),
    ]


def is_discovery_complete(context: ProjectContext) -> bool:
    return all(q.status != QuestionStatus.PENDING for q in context.discovery_questions)


def run_discovery(context: ProjectContext, idea_text: str) -> ProjectContext:
    context = intake_idea(context, idea_text)
    context = classify_domain(context)
    context = generate_discovery_questions(context)
    return context


if __name__ == "__main__":
    ctx = ProjectContext()
    ctx = run_discovery(ctx, "An app where people can book home cleaners for one-off or recurring visits")
    print(f"\nDomain: {ctx.domain_classification} (confidence: {ctx.domain_confidence})")
    print(f"{len(ctx.discovery_questions)} questions generated")

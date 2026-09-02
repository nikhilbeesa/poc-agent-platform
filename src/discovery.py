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
    context.discovery_questions = questions
    log_agent_call(logger, context.project_id, "discovery_engine", "completed", {"step": "generate_questions", "count": len(questions)})
    return context


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

Respond ONLY with JSON, no other text:
{{"questions": [{{"id": "short_id", "text": "...", "category": "..."}}]}}"""
    text = client.generate(prompt, max_tokens=3000)
    data = json.loads(text)
    return [DiscoveryQuestion(**q) for q in data["questions"]]


def _mock_followups(context: ProjectContext) -> list[DiscoveryQuestion]:
    return [
        DiscoveryQuestion(id="mock_scale", text="Roughly how many users do you expect in the first 6 months?", category="scale"),
        DiscoveryQuestion(id="mock_platform", text="Web, mobile app, or both?", category="platform"),
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

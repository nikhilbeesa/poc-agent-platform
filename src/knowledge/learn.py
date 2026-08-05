"""
Learn New Domain
=================
When discovery encounters a business idea that doesn't fit any known
domain, this analyses the idea and writes a new domain entry — description,
typical modules, seed questions — straight into the KnowledgeStore.

This is Section 7 of the spec, verbatim: "Unknown domains should be
analysed and incorporated without changing the platform architecture."
No code changes happen here — only new data gets added. The next idea
that looks like this one will match an existing domain instead of
falling through again.

Same live/mock pattern as everything else: real LLM call if
ANTHROPIC_API_KEY is set, deterministic mock output otherwise.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.store import get_knowledge_store  # noqa: E402
from llm_client import call_llm, get_client  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def learn_domain(idea_text: str, proposed_name: str, project_id: str,
                  store=None) -> dict:
    """Analyse an unrecognised idea and persist a new domain entry.
    Returns the saved domain dict plus its storage slug."""
    store = store or get_knowledge_store()

    log_agent_call(logger, project_id, "knowledge_engine", "started",
                    {"step": "learn_domain", "proposed_name": proposed_name})

    client = get_client()
    if client is None:
        domain_data = _mock_learn(idea_text, proposed_name)
    else:
        domain_data = _live_learn(client, idea_text, proposed_name)

    slug = _slugify(domain_data.get("name", proposed_name))
    store.save_domain(slug, domain_data)

    log_agent_call(logger, project_id, "knowledge_engine", "completed",
                    {"step": "learn_domain", "domain_slug": slug})
    return {"slug": slug, **domain_data}


def _live_learn(client, idea_text: str, proposed_name: str) -> dict:
    prompt = f"""This business idea doesn't clearly match any known domain:
"{idea_text}"

Propose a new domain category for it, in the same shape as an existing
domain knowledge entry: a name, a short description, the typical
functional modules businesses like this usually need, and 3-5 baseline
discovery questions worth asking any business in this domain.

Respond ONLY with JSON in exactly this shape:
{{
  "name": "Short Domain Name",
  "description": "...",
  "typical_modules": ["...", "..."],
  "seed_questions": [{{"id": "short_id", "text": "...", "category": "..."}}]
}}"""

    raw = call_llm(client, prompt, max_tokens=600)
    return json.loads(raw)


def _mock_learn(idea_text: str, proposed_name: str) -> dict:
    """Deterministic stand-in for the LLM's domain analysis."""
    slug = _slugify(proposed_name)
    return {
        "name": proposed_name.replace("_", " ").title(),
        "description": f"A newly-learned domain, inferred from an idea that didn't match existing domains: \"{idea_text}\"",
        "typical_modules": [
            "core workflow",
            "user accounts",
            "notifications",
        ],
        "seed_questions": [
            {"id": f"{slug}_users", "text": "Who are the primary users of this platform?", "category": "users"},
            {"id": f"{slug}_value", "text": "What's the core value this delivers to those users?", "category": "value_proposition"},
            {"id": f"{slug}_scale", "text": "Roughly how many users/transactions do you expect early on?", "category": "scale"},
        ],
    }


if __name__ == "__main__":
    store = get_knowledge_store()
    result = learn_domain(
        idea_text="A tool that helps small farms track crop yields and equipment maintenance",
        proposed_name="agriculture_management",
        project_id="demo-learn-1",
        store=store,
    )
    print(json.dumps(result, indent=2))
    print(f"\nStore now has: {store.list_domains()}")

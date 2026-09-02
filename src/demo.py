"""
Live Demo Script — narrated, presentation-friendly walkthrough of the
full 5-agent / 5-document pipeline.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import AgentRole, ProjectContext, ProjectStage  # noqa: E402
from discovery import is_discovery_complete, run_discovery  # noqa: E402
from export import export_all_artefacts, save_artefacts_to_disk  # noqa: E402
from orchestrator import AGENT_PIPELINE  # noqa: E402
from knowledge.store import get_knowledge_store  # noqa: E402
from knowledge.bootstrap_seed_data import bootstrap  # noqa: E402
import llm_client  # noqa: E402

DEFAULT_IDEA = "A platform where people can rent out their driveways for parking by the hour"

AGENT_LABELS = {
    AgentRole.BUSINESS_ANALYST: "Business Analyst        -> Business Requirements",
    AgentRole.PRODUCT_MANAGER: "Product Manager           -> User Stories",
    AgentRole.PRODUCT_REQUIREMENTS: "Product Requirements       -> PRD",
    AgentRole.UX_PRODUCT_FLOW: "UX / Product Flow            -> UX Product Flow Spec",
    AgentRole.AI_HANDOFF_VALIDATION: "AI Handoff Validation           -> Handoff Validation Report",
}


def _header(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)
    time.sleep(0.5)


def _step(text: str) -> None:
    print(f"\n-> {text}")
    time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--idea", type=str, default=None)
    args = parser.parse_args()

    logging.getLogger("poc_platform").setLevel(logging.CRITICAL)

    mode = "LIVE (real API)" if llm_client.get_client() else "MOCK (no API key set)"

    _header("AI PRODUCT SPECIFICATION PACKAGE — LIVE DEMO")
    print(f"  Mode: {mode}")

    idea = args.idea or DEFAULT_IDEA
    if not args.idea:
        print("\n  Using sample idea (pass --idea \"...\" for your own):")
    print(f'  "{idea}"')

    _header("DISCOVERY")
    ctx = ProjectContext()
    store = bootstrap()
    known_before = set(store.list_domains())

    _step("Intaking the idea and classifying its domain...")
    ctx = run_discovery(ctx, idea)

    print(f"\n  Domain classified as: '{ctx.domain_classification}' (confidence: {ctx.domain_confidence})")
    if ctx.domain_classification not in known_before:
        print("  This didn't match an existing domain — the system just learned and persisted a new one automatically.")

    print(f"\n  Generated {len(ctx.discovery_questions)} discovery questions:\n")
    for q in ctx.discovery_questions:
        print(f"    [{q.category}] {q.text}")
        if args.interactive:
            answer = input("      > ").strip() or "(no answer given — skipping)"
            ctx.add_answer(q.id, answer)
        else:
            ctx.add_answer(q.id, f"[auto-answered for demo — {q.category}]")
        time.sleep(0.15)

    assert is_discovery_complete(ctx)
    print("\n  Discovery complete.")

    _header("THE 5-AGENT PIPELINE")
    print("  Running 5 specialist agents in sequence.\n")

    ctx.stage = ProjectStage.AGENT_PROCESSING
    for agent in AGENT_PIPELINE:
        label = AGENT_LABELS.get(agent.role, agent.role.value)
        print(f"    ... {label}", end="", flush=True)
        t0 = time.time()
        agent.run(ctx)
        elapsed = time.time() - t0
        print(f"\r    OK  {label} ({elapsed:.1f}s)" + " " * 12)
    ctx.stage = ProjectStage.REVIEW

    val = ctx.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    status = val.output.get("final_handoff_status", "unknown") if val else "unknown"
    print(f"\n  Final AI Handoff Validation status: {status}")
    for note in ctx.consistency_notes[:3]:
        print(f"    - {note}")

    _header("EXPORTED DOCUMENTS")
    ctx = export_all_artefacts(ctx)
    out_dir = f"/tmp/poc_demo_output/{ctx.project_id[:8]}"
    paths = save_artefacts_to_disk(ctx, out_dir)

    print(f"  {len(ctx.artefacts)} documents generated:\n")
    for p in paths:
        print(f"    {p}")

    _header("DONE")
    print(f"  Full documents are open-able at: {out_dir}")
    print(f"  Domain knowledge store now has: {sorted(get_knowledge_store().list_domains())}")
    print()


if __name__ == "__main__":
    main()

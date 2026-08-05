"""
Live Demo Script
=================
A narrated, presentation-friendly walkthrough of the full pipeline —
built for showing this to stakeholders, not for automated testing (see
test_end_to_end.py for that).

Two modes:
  --interactive   You type real answers to the discovery questions live.
  (default)       Auto-answers instantly, for a quick unattended run-through.

Usage:
  python3 src/demo.py                                    # quick, auto-answered
  python3 src/demo.py --interactive                       # live, you answer
  python3 src/demo.py --idea "your business idea here"     # custom idea
  python3 src/demo.py --interactive --idea "..."           # both
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


def _pause(seconds: float = 0.6) -> None:
    time.sleep(seconds)


def _header(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)
    _pause()


def _step(text: str) -> None:
    print(f"\n→ {text}")
    _pause(0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true",
                         help="Type real answers to discovery questions live")
    parser.add_argument("--idea", type=str, default=None,
                         help="Custom business idea (defaults to a sample)")
    args = parser.parse_args()

    # Quiet the file/console logger noise for a clean presentation —
    # everything still gets written to logs/agent_activity.log underneath.
    logging.getLogger("poc_platform").setLevel(logging.CRITICAL)

    mode = "LIVE (real Claude API)" if llm_client.get_client() else "MOCK (no API key set)"

    _header("AI PRODUCT ENGINEERING AGENT PLATFORM — LIVE DEMO")
    print(f"  Mode: {mode}")

    idea = args.idea or DEFAULT_IDEA
    if not args.idea:
        print(f"\n  Using sample idea (pass --idea \"...\" for your own):")
    print(f'  "{idea}"')

    # -----------------------------------------------------------------
    _header("PHASE 2 — DISCOVERY")
    ctx = ProjectContext()
    store = bootstrap()  # ensures seed domains exist before we snapshot
    known_before = set(store.list_domains())

    _step("Intaking the idea and classifying its domain...")
    ctx = run_discovery(ctx, idea)

    print(f"\n  Domain classified as: '{ctx.domain_classification}' "
          f"(confidence: {ctx.domain_confidence})")
    if ctx.domain_classification not in known_before:
        print("  ⚡ This didn't match an existing domain — the system just")
        print("     LEARNED and PERSISTED a new one automatically.")

    print(f"\n  Generated {len(ctx.discovery_questions)} discovery questions:\n")
    for q in ctx.discovery_questions:
        print(f"    [{q.category}] {q.text}")
        if args.interactive:
            answer = input("      > ").strip() or "(no answer given — skipping)"
            ctx.add_answer(q.id, answer)
        else:
            answer = f"[auto-answered for demo — {q.category}]"
            ctx.add_answer(q.id, answer)
        _pause(0.15)

    assert is_discovery_complete(ctx)
    print("\n  ✓ Discovery complete.")

    # -----------------------------------------------------------------
    _header("PHASE 3 — THE AI AGENT TEAM")
    print("  Running 5 specialist agents in sequence. Each one reads the")
    print("  shared project context — including prior agents' work.\n")

    agent_labels = {
        AgentRole.BUSINESS_ANALYST: "Business Analyst   — requirements & goals",
        AgentRole.PRODUCT_MANAGER: "Product Manager     — epics & user stories",
        AgentRole.SOLUTION_ARCHITECT: "Solution Architect  — recommended approach",
        AgentRole.SECURITY: "Security             — risk & compliance review",
        AgentRole.QA_REVIEWER: "QA / Reviewer        — consistency check",
    }

    ctx.stage = ProjectStage.AGENT_PROCESSING
    for agent in AGENT_PIPELINE:
        label = agent_labels[agent.role]
        print(f"    ⏳ {label} ...", end="", flush=True)
        t0 = time.time()
        agent.run(ctx)
        elapsed = time.time() - t0
        print(f"\r    ✓ {label} ({elapsed:.1f}s)" + " " * 12)
    ctx.stage = ProjectStage.REVIEW

    qa = ctx.get_contribution(AgentRole.QA_REVIEWER)
    readiness = qa.output.get("overall_readiness", "unknown") if qa else "unknown"
    print(f"\n  QA verdict: {readiness.upper()}")
    for note in ctx.consistency_notes[:3]:
        print(f"    - {note}")

    # -----------------------------------------------------------------
    _header("PHASE 5 — EXPORTED ARTEFACTS")
    ctx = export_all_artefacts(ctx)
    out_dir = f"/tmp/poc_demo_output/{ctx.project_id[:8]}"
    paths = save_artefacts_to_disk(ctx, out_dir)

    print(f"  {len(ctx.artefacts)} documents generated:\n")
    for p in paths:
        print(f"    {p}")

    print("\n  Preview — Business Requirements Document:\n")
    print("  " + "-" * 68)
    for line in ctx.artefacts[0].content_markdown.strip().split("\n")[:14]:
        print(f"  {line}")
    print("  ...")
    print("  " + "-" * 68)

    # -----------------------------------------------------------------
    _header("DONE")
    print(f"  Full documents are open-able at: {out_dir}")
    print(f"  Domain knowledge store now has: {sorted(get_knowledge_store().list_domains())}")
    print()


if __name__ == "__main__":
    main()

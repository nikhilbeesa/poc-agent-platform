"""
Quick smoke test across a few different business idea types.
Not a formal test suite (that's a Phase 5 concern) — just enough to check
the discovery engine behaves sensibly across domains before moving on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context import ProjectContext  # noqa: E402
from discovery import run_discovery  # noqa: E402

SAMPLE_IDEAS = [
    "An app where people can book home cleaners for one-off or recurring visits",
    "An online store selling handmade candles and shipping them nationwide",
    "A platform connecting freelance photographers with couples planning weddings",
    "A tool that helps small farms track crop yields and equipment maintenance",  # deliberately unseen domain
]

for idea in SAMPLE_IDEAS:
    ctx = ProjectContext()
    ctx = run_discovery(ctx, idea)
    print(f"\nIDEA: {idea}")
    print(f"  -> domain: {ctx.domain_classification} (confidence: {ctx.domain_confidence})")
    print(f"  -> {len(ctx.discovery_questions)} questions generated")
    for q in ctx.discovery_questions[:3]:
        print(f"     - [{q.category}] {q.text}")
    if len(ctx.discovery_questions) > 3:
        print(f"     ... and {len(ctx.discovery_questions) - 3} more")

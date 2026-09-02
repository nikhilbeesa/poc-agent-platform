"""
Orchestrator — sequences the 5 agents. Deterministic, no AI reasoning here.

  Business Analyst        -> no dependency, runs first
  Product Manager           -> reads Business Analyst
  Product Requirements       -> reads Business Analyst + Product Manager
  UX / Product Flow            -> reads Product Manager + Product Requirements
  AI Handoff Validation           -> reads everyone, runs last
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.business_analyst import BusinessAnalystAgent  # noqa: E402
from agents.product_manager import ProductManagerAgent  # noqa: E402
from agents.product_requirements import ProductRequirementsAgent  # noqa: E402
from agents.ux_product_flow import UXProductFlowAgent  # noqa: E402
from agents.ai_handoff_validation import AIHandoffValidationAgent  # noqa: E402
from context import ProjectContext, ProjectStage  # noqa: E402
from discovery import is_discovery_complete  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()

AGENT_PIPELINE = [
    BusinessAnalystAgent(),
    ProductManagerAgent(),
    ProductRequirementsAgent(),
    UXProductFlowAgent(),
    AIHandoffValidationAgent(),
]


def run_agent_pipeline(context: ProjectContext, require_discovery_complete: bool = True) -> ProjectContext:
    if require_discovery_complete and not is_discovery_complete(context):
        raise ValueError("Discovery is not complete — all discovery questions must be answered before running the agent pipeline.")

    context.stage = ProjectStage.AGENT_PROCESSING
    log_agent_call(logger, context.project_id, "orchestrator", "started", {"pipeline": [a.role.value for a in AGENT_PIPELINE]})

    for agent in AGENT_PIPELINE:
        agent.run(context)

    context.stage = ProjectStage.REVIEW
    log_agent_call(logger, context.project_id, "orchestrator", "completed", {"contributions": len(context.agent_contributions)})
    return context


if __name__ == "__main__":
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners, mostly recurring"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
    ]

    ctx = run_agent_pipeline(ctx)
    print(f"\nStage: {ctx.stage.value}")
    print(f"Contributions: {len(ctx.agent_contributions)}")
    for c in ctx.agent_contributions:
        print(f"[{c.agent.value}] {c.summary}")

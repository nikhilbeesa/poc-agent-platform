"""
Orchestrator — sequences agent calls. Deterministic, no AI reasoning here.
7 agents, each producing (or contributing to) one of the 7 exported documents.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.business_analyst import BusinessAnalystAgent  # noqa: E402
from agents.product_manager import ProductManagerAgent  # noqa: E402
from agents.product_requirements import ProductRequirementsAgent  # noqa: E402
from agents.solution_architect import SolutionArchitectAgent  # noqa: E402
from agents.security import SecurityAgent  # noqa: E402
from agents.qa_test_strategy import QATestStrategyAgent  # noqa: E402
from agents.qa_reviewer import QAReviewerAgent  # noqa: E402
from context import ProjectContext, ProjectStage  # noqa: E402
from discovery import is_discovery_complete  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()

# Dependency order:
#   Business Analyst     -> no dependency, runs first
#   Product Manager        -> reads Business Analyst
#   Product Requirements    -> reads Business Analyst + Product Manager
#   Solution Architect        -> reads Business Analyst + Product Requirements
#   Security                    -> reads Business Analyst + Solution Architect
#   QA Test Strategy               -> reads Product Manager + Security
#   AI Review (QA Reviewer)          -> reads everyone, runs last
AGENT_PIPELINE = [
    BusinessAnalystAgent(),
    ProductManagerAgent(),
    ProductRequirementsAgent(),
    SolutionArchitectAgent(),
    SecurityAgent(),
    QATestStrategyAgent(),
    QAReviewerAgent(),
]


def run_agent_pipeline(context: ProjectContext, require_discovery_complete: bool = True) -> ProjectContext:
    if require_discovery_complete and not is_discovery_complete(context):
        raise ValueError(
            "Discovery is not complete — all discovery questions must be "
            "answered (or explicitly skipped) before running the agent pipeline."
        )

    context.stage = ProjectStage.AGENT_PROCESSING
    log_agent_call(logger, context.project_id, "orchestrator", "started",
                    {"pipeline": [a.role.value for a in AGENT_PIPELINE]})

    for agent in AGENT_PIPELINE:
        agent.run(context)

    context.stage = ProjectStage.REVIEW
    log_agent_call(logger, context.project_id, "orchestrator", "completed",
                    {"contributions": len(context.agent_contributions)})
    return context


if __name__ == "__main__":
    from context import DiscoveryQuestion

    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners for one-off or recurring visits")
    ctx.domain_classification = "booking_platform"
    ctx.discovery_questions = [
        DiscoveryQuestion(id="q1", text="Who books?", category="users", status="answered", answer="Individual homeowners, mostly recurring"),
        DiscoveryQuestion(id="q2", text="Payment timing?", category="payments", status="answered", answer="At time of booking"),
        DiscoveryQuestion(id="q3", text="Web, mobile, or both?", category="platform", status="answered", answer="Mobile app primarily"),
    ]

    ctx = run_agent_pipeline(ctx)

    print(f"\nStage after pipeline: {ctx.stage.value}")
    print(f"Contributions collected: {len(ctx.agent_contributions)}\n")
    for c in ctx.agent_contributions:
        print(f"[{c.agent.value}] {c.summary}")

    print("\nConsistency notes:")
    for n in ctx.consistency_notes:
        print(f"  - {n}")

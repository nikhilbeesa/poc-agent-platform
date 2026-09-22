from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context import AgentContribution, AgentRole, ProjectContext  # noqa: E402
from llm_client import call_llm, get_client  # noqa: E402
from logging_config import get_logger, log_agent_call  # noqa: E402

logger = get_logger()


class BaseAgent:
    role: AgentRole = None
    max_output_tokens: int = 1200

    def build_prompt(self, context: ProjectContext) -> str:
        raise NotImplementedError

    def resolution_notes_block(self, context: ProjectContext) -> str:
        """Formats any pending conflict-resolution notes (set by a
        "Resolve Issues" pass) into a prompt block. Subclasses call this
        from build_prompt() and splice the result in near the top of the
        prompt, ahead of the normal instructions, so the model treats
        fixing these specific issues as a hard requirement rather than
        an afterthought. Returns "" when there's nothing to fix."""
        if not context.resolution_notes:
            return ""
        notes = "\n".join(f"- {n}" for n in context.resolution_notes)
        return f"""
IMPORTANT — this is a revision pass. A validation step already reviewed
the full document package and found the specific issues below. Your
output MUST resolve every one of them that is relevant to this
document, while keeping everything else consistent with what the other
documents already say. Do not introduce new inconsistencies while fixing
these:
{notes}

"""

    def mock_response(self, context: ProjectContext) -> dict:
        raise NotImplementedError

    def parse_response(self, text: str) -> dict:
        return json.loads(text)

    def run(self, context: ProjectContext) -> AgentContribution:
        log_agent_call(logger, context.project_id, self.role.value, "started")
        client = get_client()
        try:
            if client is None:
                output = self.mock_response(context)
            else:
                prompt = self.build_prompt(context)
                raw = call_llm(client, prompt, max_tokens=self.max_output_tokens)
                output = self.parse_response(raw)
        except Exception as e:
            log_agent_call(logger, context.project_id, self.role.value, "failed", {"error": str(e)})
            raise

        contribution = AgentContribution(
            agent=self.role,
            summary=output.get("summary", f"{self.role.value} contribution generated"),
            output=output,
        )
        context.add_contribution(contribution)
        log_agent_call(logger, context.project_id, self.role.value, "completed", {"summary": contribution.summary})
        return contribution

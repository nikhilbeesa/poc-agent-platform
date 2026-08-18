"""
Base Agent — every specialist agent extends this. Contract: read the
shared ProjectContext, produce a structured dict, get wrapped in an
AgentContribution and appended back onto the context.
"""

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
    role: AgentRole = None  # set by subclass
    max_output_tokens: int = 1200  # override in subclasses that produce longer documents

    def build_prompt(self, context: ProjectContext) -> str:
        raise NotImplementedError

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

        log_agent_call(logger, context.project_id, self.role.value, "completed",
                        {"summary": contribution.summary})
        return contribution

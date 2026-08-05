"""
Base Agent
==========
Every specialist agent (Business Analyst, Solution Architect, Security,
Product Manager, QA) extends this. The contract is deliberately narrow:

- Input: the shared ProjectContext (idea, domain, answered questions,
  and any prior agents' contributions it needs to read)
- Output: a structured dict (agent-specific shape), wrapped in an
  AgentContribution and appended back onto the context

This is what makes agents swappable/addable without touching the
orchestrator: as long as an agent implements build_prompt, parse_response,
and mock_response, it plugs into the pipeline.
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

    def build_prompt(self, context: ProjectContext) -> str:
        """Return the prompt to send to the LLM. Must instruct it to
        respond with JSON matching this agent's expected output shape."""
        raise NotImplementedError

    def mock_response(self, context: ProjectContext) -> dict:
        """Deterministic stand-in output used when no API key is set."""
        raise NotImplementedError

    def parse_response(self, text: str) -> dict:
        """Default JSON parsing — override if an agent needs something else."""
        return json.loads(text)

    def run(self, context: ProjectContext) -> AgentContribution:
        log_agent_call(logger, context.project_id, self.role.value, "started")

        client = get_client()
        try:
            if client is None:
                output = self.mock_response(context)
            else:
                prompt = self.build_prompt(context)
                raw = call_llm(client, prompt)
                output = self.parse_response(raw)
        except Exception as e:
            log_agent_call(logger, context.project_id, self.role.value, "failed",
                            {"error": str(e)})
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

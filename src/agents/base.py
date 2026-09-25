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
        "Resolve Issues" pass) into a prompt block, together with this
        agent's own PREVIOUS output for this document (if any) — so a
        revision pass edits the existing document to fix exactly the
        issues named, rather than regenerating the whole thing from
        scratch. Regenerating from scratch each round is why a resolve
        loop can fail to converge: two independently-regenerated documents
        (e.g. the PRD's navigation pattern and the UX spec's navigation
        pattern) can each individually look reasonable while still
        disagreeing with each other, because neither was anchored to a
        fixed prior version — the "fix" just relocates the mismatch
        instead of closing it. Subclasses call this from build_prompt()
        and splice the result in near the top of the prompt, ahead of the
        normal instructions. Returns "" when there's nothing to fix."""
        if not context.resolution_notes and not context.locked_decisions:
            return ""
        notes = "\n".join(f"- {n}" for n in context.resolution_notes)
        locked_block = ""
        if context.locked_decisions:
            locked = "\n".join(f"- {n}" for n in context.locked_decisions)
            locked_block = f"""
CONFIRMED DECISIONS FROM EARLIER RESOLUTION ROUNDS — these are already
settled and MUST NOT be re-litigated, reversed, or drifted away from in
this revision, even though none of them may be mentioned in the current
issue list below (they're included here purely so an unrelated fix in
this round doesn't accidentally undo a past one):
{locked}
"""
        previous = context.get_contribution(self.role)
        previous_block = ""
        if previous is not None:
            previous_block = f"""
Your own PREVIOUS output for this document (before this revision) was:
{json.dumps(previous.output, indent=2)}

Treat the above as the current source of truth for everything you are NOT
explicitly told to change below. Make the smallest edit that fully
resolves every issue listed — keep every ID, name, and piece of content
that isn't implicated by an issue exactly as it was. Do not regenerate
unrelated sections from scratch, rename things that weren't flagged, or
introduce different wording for content the issues don't mention — doing
so creates a brand-new inconsistency in place of the one you just fixed.
"""
        current_block = ""
        if notes:
            current_block = f"""
IMPORTANT — this is a revision pass. A validation step already reviewed
the full document package and found the specific issues below. Your
output MUST resolve every one of them that is relevant to this
document, while keeping everything else consistent with what the other
documents already say. Do not introduce new inconsistencies while fixing
these:
{notes}
"""
        return f"""
{locked_block}{current_block}{previous_block}
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

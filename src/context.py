"""
Shared Project Context
=======================
This is the single "notebook" that every AI agent reads from and writes to.
No agent talks to another agent directly — they all talk through this object.
That keeps the system simple: adding a new agent later just means giving it
read/write access to the parts of this context it needs.

Design principle from the spec: "AI is used where reasoning adds value;
deterministic logic remains in the application." This file is pure
deterministic logic — validation, structure, versioning. No AI here.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProjectStage(str, Enum):
    INTAKE = "intake"
    DISCOVERY = "discovery"
    AGENT_PROCESSING = "agent_processing"
    REVIEW = "review"
    COMPLETE = "complete"


class AgentRole(str, Enum):
    BUSINESS_ANALYST = "business_analyst"
    PRODUCT_MANAGER = "product_manager"
    PRODUCT_REQUIREMENTS = "product_requirements"  # PRD agent
    SOLUTION_ARCHITECT = "solution_architect"
    SECURITY = "security"
    QA_TEST_STRATEGY = "qa_test_strategy"          # test strategy + test cases
    QA_REVIEWER = "qa_reviewer"                     # final AI Review Report — reads everyone


class QuestionStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class DiscoveryQuestion(BaseModel):
    id: str
    text: str
    category: str
    status: QuestionStatus = QuestionStatus.PENDING
    answer: Optional[str] = None


class AgentContribution(BaseModel):
    agent: AgentRole
    summary: str
    output: dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    flagged_conflicts: list[str] = Field(default_factory=list)


class Artefact(BaseModel):
    id: str
    type: str
    title: str
    content_markdown: str
    generated_by: AgentRole
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectContext(BaseModel):
    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage: ProjectStage = ProjectStage.INTAKE

    business_idea_raw: str = ""

    domain_classification: Optional[str] = None
    domain_confidence: Optional[float] = None
    discovery_questions: list[DiscoveryQuestion] = Field(default_factory=list)

    agent_contributions: list[AgentContribution] = Field(default_factory=list)

    consistency_notes: list[str] = Field(default_factory=list)

    artefacts: list[Artefact] = Field(default_factory=list)

    def add_answer(self, question_id: str, answer: str) -> None:
        for q in self.discovery_questions:
            if q.id == question_id:
                q.answer = answer
                q.status = QuestionStatus.ANSWERED
                return
        raise ValueError(f"No question with id {question_id}")

    def add_contribution(self, contribution: AgentContribution) -> None:
        self.agent_contributions.append(contribution)

    def get_contribution(self, agent: AgentRole) -> Optional[AgentContribution]:
        for c in self.agent_contributions:
            if c.agent == agent:
                return c
        return None

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "ProjectContext":
        with open(path) as f:
            return cls.model_validate(json.load(f))


if __name__ == "__main__":
    ctx = ProjectContext(business_idea_raw="An app where people can book home cleaners")
    ctx.discovery_questions.append(
        DiscoveryQuestion(id="q1", text="Who are your target customers?", category="users")
    )
    ctx.save("/tmp/sample_context.json")
    reloaded = ProjectContext.load("/tmp/sample_context.json")
    assert reloaded.business_idea_raw == ctx.business_idea_raw
    print("Schema OK.")

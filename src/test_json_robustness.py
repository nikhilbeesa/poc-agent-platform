"""Regression: malformed / truncated LLM JSON must not crash discovery, classify, learn or base agents."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from context import ProjectContext  # noqa: E402
from discovery import _live_dynamic_questions, _live_classify  # noqa: E402
from knowledge.learn import _live_learn  # noqa: E402
from llm_client import LLMTruncated  # noqa: E402

Q = lambda i: {"id": f"q{i}", "text": f"Question {i}?", "category": "users", "options": ["a", "b"], "multi_select": False}
GOOD = json.dumps({"questions": [Q(i) for i in range(5)]})

class Fake:
    def __init__(self, replies): self.replies = list(replies); self.calls = 0
    def generate(self, prompt, max_tokens=800):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception): raise r
        return r

def ctx():
    c = ProjectContext(); c.business_idea_raw = "idea"; c.domain_classification = "x"; return c

def test():
    # 1 trailing comma + prose + fences
    bad = "Here you go:\n```json\n" + GOOD.replace("}]}", "},]}") + "\n```"
    assert len(_live_dynamic_questions(Fake([bad]), ctx(), None)) == 5
    # 2 invalid first (the reported error), valid on retry
    f = Fake(["{\"questions\": [\n  {\"id\": \"a\", \n  oops", GOOD])
    assert len(_live_dynamic_questions(f, ctx(), None)) == 5 and f.calls == 2
    # 3 truncated: keep completed questions
    partial = GOOD[: GOOD.rfind("{") + 15]
    qs = _live_dynamic_questions(Fake([LLMTruncated(partial)]), ctx(), None)
    assert len(qs) == 4, len(qs)
    # 4 missing optional fields / bad option types tolerated
    odd = json.dumps({"questions": [{"text": "Only text?"}, {"id": "z", "text": "T", "category": "c", "options": "nope"}]})
    assert len(_live_dynamic_questions(Fake([odd]), ctx(), None)) == 2
    # 5 classify + learn
    assert _live_classify(Fake(['```json\n{"domain": "d", "confidence": 0.9,}\n```']), "i", ["a"]) == ("d", 0.9)
    d = _live_learn(Fake(['{"name": "N", "description": "D", "typical_modules": ["m"], "seed_questions": [],}']), "i", "n")
    assert d["name"] == "N"
    # 6 base agent default path
    from agents.base import BaseAgent
    class A(BaseAgent):
        def build_prompt(self, c): return "p"
    f = Fake(["not json at all", '{"summary": "ok",}'])
    assert A().generate_live(ctx(), f)["summary"] == "ok" and f.calls == 2
    print("json robustness: all scenarios pass")

if __name__ == "__main__":
    test()

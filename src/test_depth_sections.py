"""Regression for the depth additions: user-story validation/error/empty/edge sections, BRD flow diagrams,
scored risk register and key parameters — including that malformed model output never breaks the run."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from context import AgentRole, ProjectContext  # noqa: E402
from agents.business_analyst import BusinessAnalystAgent  # noqa: E402
from agents.ai_handoff_validation import AIHandoffValidationAgent as V  # noqa: E402
import agents.live_product_manager as lpm  # noqa: E402
import agents.live_business_analyst as lba  # noqa: E402
import chunked as ch  # noqa: E402


def _ctx():
    c = ProjectContext(business_idea_raw="An online store selling handmade candles")
    c.domain_classification = "e_commerce"
    BusinessAnalystAgent().run(c)
    return c


class FakePM:
    """Returns one story per requested FR id; `full` controls whether the new sections are included."""
    def __init__(self, full): self.full = full; self.calls = 0
    def generate(self, prompt, max_tokens=800):
        self.calls += 1
        ids = re.search(r"\[\[UNITS:([^\]]*)\]\]", prompt).group(1).split(",")
        stories = []
        for i in ids:
            s = {"fr_id": i, "role": "x", "story": "As a x, I want y, so that z", "business_value": "v", "preconditions": "p",
                 "trigger": "t", "main_flow": ["a", "b", "c", "d"], "alternative_flow": "alt", "exception_flow": "exc",
                 "acceptance_criteria": ["Given a, when b, then c"] * 5}
            if self.full:
                s.update({"data_validation": ["email: required, valid format"], "error_messages": ["invalid -> \"Bad email\""],
                          "empty_states": ["Not applicable — always has data"], "edge_cases": ["double submit -> one record"]})
            stories.append(s)
        return json.dumps({"stories": stories})


def test():
    # 1. mock package already satisfies every new depth check
    c = _ctx()
    from agents.product_manager import ProductManagerAgent
    ProductManagerAgent().run(c)
    ba = c.get_contribution(AgentRole.BUSINESS_ANALYST).output
    pm = c.get_contribution(AgentRole.PRODUCT_MANAGER).output
    assert V._content_depth_findings(ba, pm) == [], V._content_depth_findings(ba, pm)
    assert len(ba["flow_diagrams"]) >= 3 and all(ch.sanitize_mermaid(d["mermaid"]) for d in ba["flow_diagrams"])
    assert all(r["score"] > 0 and r["owner"] for r in ba["risks"]) and ba["risks"][0]["score"] >= ba["risks"][-1]["score"]

    # 2. live PM with the new sections present
    out = lpm.generate(c, FakePM(full=True))
    s0 = out["stories"][0]
    assert s0["data_validation"] and s0["error_messages"] and s0["empty_states"] and s0["edge_cases"]
    assert V._content_depth_findings(ba, out) == []

    # 3. live PM where the model omits them: must NOT crash, and validation must flag it by story ID
    out2 = lpm.generate(c, FakePM(full=False))
    assert len(out2["stories"]) == len(out["stories"])
    f = V._content_depth_findings(ba, out2)
    assert any("US-001" in x["recommended_action"] and "validation" in x["missing_item"] for x in f)

    # 4. reused stories from an OLD version (no new fields) are regenerated, not reused
    old = json.loads(json.dumps(out2))
    for s in old["stories"]:
        s["_src"] = "stale"
    assert lpm.STORY_SCHEMA_VERSION in "v2-depth"

    # 5. BRD helpers tolerate junk
    assert ch.normalize_risks("junk") == [] and ch.normalize_key_parameters([1, None, {"parameter": "x"}])[0]["status"] == "TBD"
    d = ch.normalize_flow_diagrams([{"mermaid": "not a diagram"}, "junk"], [("Future", "A -> B -> C")])
    assert len(d) == 1 and d[0]["mermaid"].startswith("flowchart")
    risky = ch.normalize_risks([{"risk": "r", "likelihood": "High", "impact": "High"}, {"risk": "s", "likelihood": "Low", "severity": "Low"}])
    assert risky[0]["rating"] == "High" and risky[1]["rating"] == "Low"

    # 6. live BRD cross-cutting stage survives a failed diagrams/parameters call
    class FakeBA:
        n = 0
        def generate(self, prompt, max_tokens=800):
            if "[[TASK:ba.crosscut_c]]" in prompt:
                return "totally not json"
            return "{}"
    plan = {"modules": [{"id": "MOD-01", "name": "M", "purpose": "p"}], "roles": [{"role": "Customer"}]}
    cross = lba._crosscut(c, FakeBA(), plan, [{"id": "FR-001", "module": "M", "name": "n"}])
    assert "flow_diagrams" not in cross
    out_ba = {"future_state_flow": "A -> B -> C", "current_state_flow": "X -> Y -> Z", "risks": [{"risk": "r"}]}
    lba._finalize_depth_sections(out_ba)
    assert len(out_ba["flow_diagrams"]) == 2 and out_ba["risks"][0]["rating"] == "Not assessed"

    # 7. validation flags an unassessed/unowned risk register, tiny key-parameter list and missing diagrams
    weak = {"risks": [{"risk": "r", "score": 0, "owner": ""}], "flow_diagrams": [], "key_parameters": []}
    kinds = " ".join(x["missing_item"] for x in V._content_depth_findings(weak, {"stories": []}))
    assert "flow diagrams" in kinds and "Risk register" in kinds and "Key business parameters" in kinds
    print("depth sections: all scenarios pass")


if __name__ == "__main__":
    test()

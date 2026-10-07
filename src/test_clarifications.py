"""Clarifying questions: asked before the BRD, answers written into it, no Open Questions / stories sections."""
import re, sys
sys.path.insert(0, ".")
from context import ProjectContext
from discovery import run_discovery
from export import export_business_requirements
from orchestrator import run_full_pipeline
import clarifications as clar

def _project(skip_every=5):
    ctx = run_discovery(ProjectContext(), "An app where people book home cleaners and pay online")
    for i, q in enumerate(ctx.discovery_questions):
        if i % skip_every == 3: ctx.skip_question(q.id)
        else: ctx.add_answer(q.id, q.options[0] if q.options else "Test answer")
    return ctx

def test_pending_then_answered_not_asked_again():
    ctx = _project(); items = clar.pending_questions(ctx)
    assert any(i["kind"] == "discovery" for i in items) and any(i["kind"] == "parameter" for i in items)
    clar.apply_answers(ctx, [{"id": i["id"], "answer": "x" if i["kind"] == "parameter" else ""} for i in items])
    assert clar.pending_questions(ctx) == []                       # answered or skipped -> never re-asked

def test_brd_structure_and_answers():
    ctx = _project()
    param = next(i for i in clar.pending_questions(ctx) if i["kind"] == "parameter")
    clar.apply_answers(ctx, [{"id": param["id"], "answer": "Within 21 days"}])   # asked BEFORE the BRD is written
    run_full_pipeline(ctx)
    brd = export_business_requirements(ctx).content_markdown
    heads = re.findall(r"(?m)^## (.+)$", brd)
    assert not any(re.search(r"Open Questions|User Stories|Acceptance Criteria", h) for h in heads)
    assert heads[-1].endswith("Appendices")
    sub = lambda n: re.findall(rf"(?m)^### ({n}\.\d+) ", brd)
    assert len(sub(16)) == 7 and len(sub(17)) == 4             # data/notifications/payment/admin/reporting under FR; security/privacy/a11y under NFR
    assert "Within 21 days" in brd and "Confirmed — stakeholder" in brd
    ids = {m for m in re.findall(r"(?m)^#{2,3} (.+)$", brd)}
    toc = re.findall(r"\]\(#([^)]+)\)", brd)
    assert toc and len(toc) >= len(heads)


def test_ai_recommends_consistently_and_fills_blanks():
    ctx = _project(skip_every=2)
    items = clar.pending_questions(ctx)
    sug = clar.suggest(ctx, items, use_llm=False)
    for it in items:                                   # every suggestion for an options question is one of the options
        if it.get("options") and it["id"] in sug:
            assert all(p.strip() in it["options"] for p in sug[it["id"]]["suggestion"].split("|"))
    # changing one answer changes the recommendations that depend on it
    a = clar.suggest(ctx, items, {"dq:bp_cancellation": "Strict — limited or no refunds"}, use_llm=False)
    b = clar.suggest(ctx, items, {"dq:bp_cancellation": "Flexible — full refunds"}, use_llm=False)
    k = next(i for i in a if i.startswith("kp:refund"))
    assert a[k]["suggestion"] != b[k]["suggestion"]
    # leaving everything blank -> AI fills, labelled for confirmation in the BRD
    res = clar.apply_answers(ctx, [{"id": i["id"], "answer": ""} for i in items])
    assert res["ai_chosen"] > 0 and clar.pending_questions(ctx) == []
    assert any("Recommended by AI" in l for l in clar.brd_assumption_lines(ctx))

def test_rethink_fix_or_accept_never_dead_ends():
    import rethink as rt
    from agents.feasibility import FeasibilityAssessmentAgent
    ctx = _project(skip_every=2)
    for q in ctx.discovery_questions:                      # "not sure" answers create serious flaws
        unsure = next((o for o in q.options if "not sure" in o.lower() or "not decided" in o.lower()), None)
        if unsure: ctx.add_answer(q.id, unsure)
    FeasibilityAssessmentAgent().run(ctx)
    plan = rt.plan(ctx, use_llm=False)
    assert plan, "expected at least one serious flaw"
    assert all(i["key"] and i["flaw"] for i in plan)
    assert any(q["suggestion"] for i in plan for q in i["questions"]), "AI should propose a concrete answer"
    c0 = rt.counts(ctx)
    rt.apply(ctx, {}, [plan[0]["key"]])                    # knowingly accept one flaw
    assert rt.counts(ctx)["open"] == c0["open"] - 1 and rt.counts(ctx)["accepted"] == 1
    # an accepted flaw whose answers then change is open again (the acceptance no longer applies)
    linked = next((i for i in plan if i["questions"] and i["key"] != plan[0]["key"]), None)
    if linked:
        rt.apply(ctx, {}, [linked["key"]]); before = rt.counts(ctx)["accepted"]
        q = linked["questions"][0]; new = next(o for o in q["options"] if o != q["current"]) if q["options"] else "different answer"
        rt.apply(ctx, {q["id"]: new}, [])
        assert rt.counts(ctx)["accepted"] < before

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("PASS ", n)

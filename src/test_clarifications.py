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

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("PASS ", n)

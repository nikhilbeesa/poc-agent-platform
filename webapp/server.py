"""
Local/Hosted Web Demo Server — thin Flask API over the pipeline
(discovery, 6 agents — feasibility check first, then the 4 specification agents and the
handoff validation — and export of the 6-document package).
"""

import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from context import (  # noqa: E402
    AgentRole, Artefact, DiscoveryQuestion, ProjectContext, ProjectStage,
)
from discovery import is_discovery_complete, run_discovery  # noqa: E402
from export import export_all_artefacts  # noqa: E402
from knowledge.bootstrap_seed_data import bootstrap  # noqa: E402
from knowledge.store import get_knowledge_store  # noqa: E402
from llm_client import get_client  # noqa: E402
from orchestrator import AGENT_PIPELINE, resolve_handoff_issues  # noqa: E402
import jobs  # noqa: E402
from project_store import get_project_store  # noqa: E402

app = Flask(__name__, static_folder=str(Path(__file__).resolve().parent / "static"))


@app.errorhandler(Exception)
def handle_any_error(e):
    """Every unhandled error comes back as readable JSON instead of an
    HTML error page, which breaks the frontend's res.json() parsing."""
    import traceback
    traceback.print_exc()
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


PROJECTS: dict = {}
DEMO_DELAY = 0.5


# Per-project data that has no home on ProjectContext but must survive a re-save
# (e.g. the agent log / handoff verdict of an already-generated project that was
# reopened for editing and has not been re-run yet).
META: dict = {}

_ROLE_BY_ARTEFACT_TYPE = {
    "feasibility_assessment": AgentRole.FEASIBILITY_ASSESSMENT,
    "business_requirements": AgentRole.BUSINESS_ANALYST,
    "user_stories": AgentRole.PRODUCT_MANAGER,
    "prd": AgentRole.PRODUCT_REQUIREMENTS,
    "ux_product_flow_specification": AgentRole.UX_PRODUCT_FLOW,
    "ai_handoff_validation": AgentRole.AI_HANDOFF_VALIDATION,
}


def _question_dicts(ctx):
    return [
        {"id": q.id, "text": q.text, "category": q.category, "status": q.status.value, "options": q.options,
         "multi_select": q.multi_select, "answer": q.answer}
        for q in ctx.discovery_questions
    ]


def _feasibility_summary(ctx):
    """The small slice of the feasibility assessment the UI shows right after it runs (and on reopen)."""
    c = ctx.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    if not c:
        return None
    o = c.output
    return {"verdict": o.get("verdict"), "rationale": o.get("verdict_rationale"), "confidence": o.get("confidence"),
            "counts": o.get("counts"), "headline_flaws": o.get("headline_flaws") or [],
            "recommended_changes": (o.get("recommended_changes") or [])[:3]}


def _record_from_ctx(ctx) -> dict:
    """Everything needed to show, resume, edit and re-run a project later."""
    meta = META.get(ctx.project_id, {})
    if ctx.agent_contributions:
        label_by_role = {m["role"]: m["label"] for m in AGENT_META}
        agent_log = [{"agent": c.agent.value, "label": label_by_role.get(c.agent.value, c.agent.value), "summary": c.summary}
                     for c in ctx.agent_contributions]
        val = ctx.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
        handoff_status = val.output.get("final_handoff_status") if val else meta.get("handoff_status")
    else:
        agent_log = meta.get("agent_log", [])
        handoff_status = meta.get("handoff_status")
    return {
        "id": ctx.project_id,
        "business_idea": ctx.business_idea_raw,
        "domain": ctx.domain_classification,
        "domain_confidence": ctx.domain_confidence,
        "stage": ctx.stage.value,
        "status": "complete" if ctx.artefacts else "draft",
        "handoff_status": handoff_status,
        "consistency_notes": ctx.consistency_notes,
        "system_profile": ctx.system_profile,
        "feasibility": _feasibility_summary(ctx) or meta.get("feasibility"),
        "created_at": ctx.created_at.isoformat(),
        "questions": _question_dicts(ctx),
        "agent_log": agent_log,
        "artefacts": [
            {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
            for a in ctx.artefacts
        ],
    }


def _persist(ctx, strict: bool = False) -> None:
    """Saves the project. Draft autosaves (every answer) are best-effort so a storage
    hiccup never blocks the questionnaire; exports pass strict=True."""
    try:
        get_project_store().save(_record_from_ctx(ctx))
    except Exception:  # noqa: BLE001
        if strict:
            raise
        import traceback
        traceback.print_exc()


def _ctx_from_record(rec: dict) -> ProjectContext:
    """Rebuilds a working ProjectContext from a saved record so a draft can be
    resumed, or a finished project's answers edited and its agents re-run."""
    ctx = ProjectContext(
        project_id=rec["id"], business_idea_raw=rec.get("business_idea") or "",
        domain_classification=rec.get("domain"), domain_confidence=rec.get("domain_confidence"),
        stage=ProjectStage.DISCOVERY,
    )
    if rec.get("created_at"):
        try:
            from datetime import datetime
            ctx.created_at = datetime.fromisoformat(str(rec["created_at"]).replace("Z", "+00:00"))
        except ValueError:
            pass
    ctx.discovery_questions = [DiscoveryQuestion(**{k: q.get(k) for k in ("id", "text", "category", "status", "answer", "options", "multi_select") if q.get(k) is not None})
                               for q in (rec.get("questions") or [])]
    ctx.consistency_notes = list(rec.get("consistency_notes") or [])
    ctx.system_profile = rec.get("system_profile") or None
    ctx.artefacts = [
        Artefact(id=f"{rec['id']}-{a.get('type')}", type=a.get("type", ""), title=a.get("title", ""),
                 content_markdown=a.get("content_markdown", ""),
                 generated_by=_ROLE_BY_ARTEFACT_TYPE.get(a.get("type"), AgentRole.AI_HANDOFF_VALIDATION))
        for a in (rec.get("artefacts") or [])
    ]
    META[rec["id"]] = {"agent_log": rec.get("agent_log") or [], "handoff_status": rec.get("handoff_status"),
                       "feasibility": rec.get("feasibility")}
    return ctx


def _get_ctx(project_id):
    """The live context for a project; if the server restarted since, it is rebuilt
    from the saved record so a draft can carry on where it left off."""
    ctx = PROJECTS.get(project_id)
    if ctx is None:
        rec = get_project_store().get(project_id)
        if rec:
            ctx = PROJECTS[project_id] = _ctx_from_record(rec)
    return ctx


def _demo_pace():
    if get_client() is None:
        time.sleep(DEMO_DELAY)


def _run_maybe_async(project_id, work):
    """Mock mode is instant, so it answers directly. Live mode makes many LLM
    calls (minutes), so it becomes a background job the browser polls — see
    jobs.py."""
    if get_client() is None:
        return jsonify(work())
    return jsonify({"job_id": jobs.start(project_id, work), "async": True}), 202


AGENT_META = [
    {"role": "feasibility_assessment", "label": "Feasibility Check", "note": "will it work? competitors"},
    {"role": "business_analyst", "label": "Business Analyst", "note": "business requirements"},
    {"role": "product_manager", "label": "Product Manager", "note": "user stories"},
    {"role": "product_requirements", "label": "Product Requirements", "note": "PRD"},
    {"role": "ux_product_flow", "label": "UX / Product Flow", "note": "screens, flows, states"},
    {"role": "ai_handoff_validation", "label": "AI Handoff Validation", "note": "final readiness check"},
]


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/mode")
def mode():
    client = get_client()
    if client is None:
        return jsonify({"mode": "mock", "provider": None})
    return jsonify({"mode": "live", "provider": client.provider})


@app.route("/api/knowledge/domains")
def knowledge_domains():
    return jsonify({"domains": get_knowledge_store().list_domains()})


@app.route("/api/project", methods=["POST"])
def create_project():
    data = request.get_json(force=True)
    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"error": "idea is required"}), 400

    store = bootstrap()
    known_before = set(store.list_domains())

    _demo_pace()
    ctx = ProjectContext()
    ctx = run_discovery(ctx, idea)
    PROJECTS[ctx.project_id] = ctx

    learned = ctx.domain_classification not in known_before
    _persist(ctx)   # the project exists as a resumable draft from the first moment

    return jsonify({
        "project_id": ctx.project_id,
        "domain": ctx.domain_classification,
        "confidence": ctx.domain_confidence,
        "learned_new_domain": learned,
        "questions": [
            {"id": q.id, "text": q.text, "category": q.category, "status": q.status.value, "options": q.options, "multi_select": q.multi_select}
            for q in ctx.discovery_questions
        ],
    })


@app.route("/api/project/<project_id>/answer", methods=["POST"])
def answer_question(project_id):
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    data = request.get_json(force=True)
    question_id = data.get("question_id")
    answer = (data.get("answer") or "").strip() or "(no answer provided)"
    try:
        ctx.add_answer(question_id, answer)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    _persist(ctx)
    return jsonify({"question_id": question_id, "status": "answered", "discovery_complete": is_discovery_complete(ctx)})


@app.route("/api/project/<project_id>/skip", methods=["POST"])
def skip_question(project_id):
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    data = request.get_json(force=True)
    question_id = data.get("question_id")
    try:
        ctx.skip_question(question_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    _persist(ctx)
    return jsonify({"question_id": question_id, "status": "skipped", "discovery_complete": is_discovery_complete(ctx)})


@app.route("/api/project/<project_id>/agents", methods=["GET"])
def list_agents(project_id):
    return jsonify({"agents": AGENT_META})


@app.route("/api/project/<project_id>/agent/<int:index>", methods=["POST"])
def run_agent(project_id, index):
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if not is_discovery_complete(ctx):
        return jsonify({"error": "discovery is not complete yet"}), 400
    if index < 0 or index >= len(AGENT_PIPELINE):
        return jsonify({"error": "invalid agent index"}), 400
    if index == 0:
        # A fresh run (first run, or a re-run after answers were edited) always starts
        # from a clean slate. The previously saved artefacts and agent log deliberately
        # stay in place until the new export replaces them, so a failed re-run can
        # never leave the project without its last good package.
        if jobs.is_running(project_id):
            return jsonify({"error": "The AI agents are already running for this project."}), 409
        ctx.agent_contributions = []
        ctx.consistency_notes = []
        ctx.resolution_notes = []
        ctx.locked_decisions = []
        ctx.system_profile = None   # rebuilt from the (possibly edited) answers by the first agent
        ctx.stage = ProjectStage.AGENT_PROCESSING
    if index != len(ctx.agent_contributions):
        return jsonify({"error": f"agents must run in order — expected index {len(ctx.agent_contributions)}"}), 400

    _demo_pace()

    def work():
        # NOTE: the last agent deliberately runs validation ONCE here and does
        # not chain the multi-round gap-correction loop — auto-repair is a
        # short chain of separate /resolve requests driven by the frontend
        # (see runAgentPipeline() in app.js), so no single request or job
        # grows without bound.
        agent = AGENT_PIPELINE[index]
        contribution = agent.run(ctx)
        return {
            "agent": contribution.agent.value,
            "summary": contribution.summary,
            # the UI only needs the full output for the validator's verdict; the
            # content agents' outputs run to megabytes at full depth
            "output": contribution.output if contribution.agent == AgentRole.AI_HANDOFF_VALIDATION else {},
            "consistency_notes": ctx.consistency_notes if contribution.agent == AgentRole.AI_HANDOFF_VALIDATION else [],
            "feasibility": _feasibility_summary(ctx) if contribution.agent == AgentRole.FEASIBILITY_ASSESSMENT else None,
        }

    return _run_maybe_async(project_id, work)


@app.route("/api/project/<project_id>/export", methods=["POST"])
def export(project_id):
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if len(ctx.agent_contributions) < len(AGENT_PIPELINE):
        return jsonify({"error": "agent pipeline is not complete yet"}), 400

    _demo_pace()
    ctx = export_all_artefacts(ctx)

    val = ctx.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    handoff_status = val.output.get("final_handoff_status") if val else None
    capability_summary = val.output.get("capability_summary") if val else None
    outstanding_capabilities = sorted(set((val.output.get("missing_capabilities", []) if val else [])) |
                                       set((val.output.get("partial_capabilities", []) if val else [])))

    _persist(ctx, strict=True)

    # stage is the authoritative completeness gate: COMPLETE only when the
    # AI Handoff Validation agent's deterministic-matrix-backed verdict is
    # genuinely clean (see orchestrator.run_gap_correction_loop / export.py).
    # The documents existing is necessary but never sufficient on its own —
    # callers should check "stage", not just that this call returned 200.
    return jsonify({
        "stage": ctx.stage.value,
        "feasibility": _feasibility_summary(ctx),
        "is_complete": ctx.stage.value == "complete",
        "handoff_status": handoff_status,
        "capability_summary": capability_summary,
        "outstanding_capabilities": outstanding_capabilities,
        "artefacts": [
            {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
            for a in ctx.artefacts
        ]
    })


@app.route("/api/project/<project_id>/resolve", methods=["POST"])
def resolve_issues(project_id):
    """Re-runs exactly the agent(s) implicated by the latest AI Handoff
    Validation's conflicts/missing-information (plus anything downstream
    of them), re-validates, and regenerates the specification documents so the
    person gets a corrected package rather than just an updated warning
    list."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if len(ctx.agent_contributions) < len(AGENT_PIPELINE):
        return jsonify({"error": "agent pipeline is not complete yet"}), 400

    _demo_pace()

    def work():
        result = resolve_handoff_issues(ctx)
        if not result.get("resolved"):
            return result
        export_all_artefacts(ctx)
        val = ctx.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)

        _persist(ctx, strict=True)

        return {
            **result,
            "validation_output": val.output if val else None,
            "consistency_notes": ctx.consistency_notes,
            "agents": [
                {"agent": c.agent.value, "summary": c.summary}
                for c in ctx.agent_contributions
            ],
            "artefacts": [
                {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
                for a in ctx.artefacts
            ],
        }

    return _run_maybe_async(project_id, work)


@app.route("/api/project/<project_id>/session", methods=["GET"])
def project_session(project_id):
    """Reopens a saved project (an unfinished draft or a finished one) as a live
    session: rebuilds the working context from storage so the person can carry on
    answering, edit answers, and re-run the agents. Also returns everything needed
    to show the whole process — questions + answers, the agent run, the artefacts."""
    rec = get_project_store().get(project_id)
    if not rec:
        return jsonify({"error": "project not found"}), 404
    running = jobs.is_running(project_id)
    if not (running and project_id in PROJECTS):
        PROJECTS[project_id] = _ctx_from_record(rec)
    ctx = PROJECTS[project_id]
    return jsonify({
        "project_id": project_id,
        "business_idea": rec.get("business_idea"),
        "domain": rec.get("domain"),
        "confidence": rec.get("domain_confidence"),
        "status": rec.get("status") or ("complete" if rec.get("artefacts") else "draft"),
        "handoff_status": rec.get("handoff_status"),
        "consistency_notes": rec.get("consistency_notes") or [],
        "created_at": rec.get("created_at"),
        "agents_running": running,
        "feasibility": rec.get("feasibility"),
        "questions": _question_dicts(ctx),
        "agent_log": rec.get("agent_log") or [],
        "artefacts": rec.get("artefacts") or [],
    })


@app.route("/api/project/<project_id>", methods=["DELETE"])
def discard_draft(project_id):
    """Discards an UNFINISHED draft. Projects that already have generated artefacts
    are never deleted through this endpoint."""
    rec = get_project_store().get(project_id)
    if not rec:
        return jsonify({"error": "project not found"}), 404
    if rec.get("artefacts"):
        return jsonify({"error": "Only unfinished drafts can be discarded."}), 400
    if jobs.is_running(project_id):
        return jsonify({"error": "The AI agents are still running for this project."}), 409
    get_project_store().delete(project_id)
    PROJECTS.pop(project_id, None)
    META.pop(project_id, None)
    return jsonify({"discarded": project_id})


@app.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id):
    snap = jobs.snapshot(job_id)
    if snap is None:
        return jsonify({"error": "unknown or expired job"}), 404
    return jsonify(snap)


@app.route("/api/history", methods=["GET"])
def history_list():
    return jsonify({"projects": get_project_store().list_summaries()})


@app.route("/api/history/<project_id>", methods=["GET"])
def history_detail(project_id):
    record = get_project_store().get(project_id)
    if not record:
        return jsonify({"error": "project not found"}), 404
    return jsonify(record)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("\n  AI Product Specification Package — local demo server")
    print(f"  Running in {'LIVE' if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('GEMINI_API_KEY') else 'MOCK'} mode")
    print(f"  Open: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

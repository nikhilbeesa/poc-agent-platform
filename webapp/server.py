"""
Local/Hosted Web Demo Server — thin Flask API over the pipeline
(discovery, 5 agents, export of the 5-document package).
"""

import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from context import AgentRole, ProjectContext  # noqa: E402
from discovery import is_discovery_complete, run_discovery  # noqa: E402
from export import export_all_artefacts  # noqa: E402
from knowledge.bootstrap_seed_data import bootstrap  # noqa: E402
from knowledge.store import get_knowledge_store  # noqa: E402
from llm_client import get_client  # noqa: E402
from orchestrator import AGENT_PIPELINE  # noqa: E402
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


def _demo_pace():
    if get_client() is None:
        time.sleep(DEMO_DELAY)


AGENT_META = [
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

    return jsonify({
        "project_id": ctx.project_id,
        "domain": ctx.domain_classification,
        "confidence": ctx.domain_confidence,
        "learned_new_domain": learned,
        "questions": [
            {"id": q.id, "text": q.text, "category": q.category, "status": q.status.value}
            for q in ctx.discovery_questions
        ],
    })


@app.route("/api/project/<project_id>/answer", methods=["POST"])
def answer_question(project_id):
    ctx = PROJECTS.get(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    data = request.get_json(force=True)
    question_id = data.get("question_id")
    answer = (data.get("answer") or "").strip() or "(no answer provided)"
    try:
        ctx.add_answer(question_id, answer)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"question_id": question_id, "status": "answered", "discovery_complete": is_discovery_complete(ctx)})


@app.route("/api/project/<project_id>/agents", methods=["GET"])
def list_agents(project_id):
    return jsonify({"agents": AGENT_META})


@app.route("/api/project/<project_id>/agent/<int:index>", methods=["POST"])
def run_agent(project_id, index):
    ctx = PROJECTS.get(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if not is_discovery_complete(ctx):
        return jsonify({"error": "discovery is not complete yet"}), 400
    if index < 0 or index >= len(AGENT_PIPELINE):
        return jsonify({"error": "invalid agent index"}), 400
    if index != len(ctx.agent_contributions):
        return jsonify({"error": f"agents must run in order — expected index {len(ctx.agent_contributions)}"}), 400

    _demo_pace()
    agent = AGENT_PIPELINE[index]
    contribution = agent.run(ctx)

    return jsonify({
        "agent": contribution.agent.value,
        "summary": contribution.summary,
        "output": contribution.output,
        "consistency_notes": ctx.consistency_notes if contribution.agent == AgentRole.AI_HANDOFF_VALIDATION else [],
    })


@app.route("/api/project/<project_id>/export", methods=["POST"])
def export(project_id):
    ctx = PROJECTS.get(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if len(ctx.agent_contributions) < len(AGENT_PIPELINE):
        return jsonify({"error": "agent pipeline is not complete yet"}), 400

    _demo_pace()
    ctx = export_all_artefacts(ctx)

    val = ctx.get_contribution(AgentRole.AI_HANDOFF_VALIDATION)
    handoff_status = val.output.get("final_handoff_status") if val else None

    store = get_project_store()
    store.save({
        "id": ctx.project_id,
        "business_idea": ctx.business_idea_raw,
        "domain": ctx.domain_classification,
        "domain_confidence": ctx.domain_confidence,
        "stage": ctx.stage.value,
        "handoff_status": handoff_status,
        "consistency_notes": ctx.consistency_notes,
        "artefacts": [
            {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
            for a in ctx.artefacts
        ],
    })

    return jsonify({
        "artefacts": [
            {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
            for a in ctx.artefacts
        ]
    })


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

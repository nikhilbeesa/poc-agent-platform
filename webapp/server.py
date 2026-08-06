"""
Local Web Demo Server
=======================
Thin Flask API over the existing pipeline (discovery, agents, export).
Runs entirely locally, no API key required — uses mock mode throughout.

Each agent runs via its own endpoint call rather than one big "run
everything" call, so the frontend can show real step-by-step progress
instead of a single spinner.

Run with:  python3 webapp/server.py
Then open: http://localhost:5001
"""

import os
import sys
import time
import uuid
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

app = Flask(__name__, static_folder=str(Path(__file__).resolve().parent / "static"))


@app.errorhandler(Exception)
def handle_any_error(e):
    """Flask's default error page is HTML — that's what caused the
    'Unexpected token <' error in the browser, because the frontend
    always expects JSON back from /api/* routes. This makes every
    unhandled error (missing env vars, a bad Supabase URL, an LLM API
    error, anything) come back as readable JSON with the real message,
    so it actually shows up in the UI instead of a cryptic parse error."""
    import traceback
    traceback.print_exc()  # full traceback still goes to Render's logs
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


# In-memory project store — fine for a local single-user demo.
PROJECTS: dict[str, ProjectContext] = {}

# Small artificial delay so MOCK mode doesn't feel instantaneous/
# anticlimactic in a live demo. Live mode already has genuine API
# latency, so this is skipped there — see _demo_pace().
DEMO_DELAY = 0.5


def _demo_pace():
    if get_client() is None:
        time.sleep(DEMO_DELAY)

AGENT_META = [
    {"role": "business_analyst", "label": "Business Analyst", "note": "requirements & goals"},
    {"role": "product_manager", "label": "Product Manager", "note": "epics & user stories"},
    {"role": "solution_architect", "label": "Solution Architect", "note": "recommended approach"},
    {"role": "security", "label": "Security", "note": "risk & compliance review"},
    {"role": "qa_reviewer", "label": "QA / Reviewer", "note": "consistency check"},
]


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/mode")
def mode():
    client = get_client()
    if client is None:
        return jsonify({"mode": "mock", "provider": None})
    return jsonify({"mode": "live", "provider": client.provider})


@app.route("/api/knowledge/domains")
def knowledge_domains():
    store = get_knowledge_store()
    return jsonify({"domains": store.list_domains()})


@app.route("/api/project", methods=["POST"])
def create_project():
    data = request.get_json(force=True)
    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"error": "idea is required"}), 400

    store = bootstrap()  # ensures the 3 seed domains exist before we snapshot
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

    return jsonify({
        "question_id": question_id,
        "status": "answered",
        "discovery_complete": is_discovery_complete(ctx),
    })


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
        "consistency_notes": ctx.consistency_notes if contribution.agent == AgentRole.QA_REVIEWER else [],
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

    return jsonify({
        "artefacts": [
            {"type": a.type, "title": a.title, "content_markdown": a.content_markdown}
            for a in ctx.artefacts
        ]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("\n  AI Product Engineering Agent Platform — local demo server")
    print(f"  Running in {'LIVE' if os.environ.get('ANTHROPIC_API_KEY') else 'MOCK'} mode")
    print(f"  Open: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

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
import clarifications as clar  # noqa: E402
import rethink as rt  # noqa: E402
from integrations import sync as backlog_sync  # noqa: E402
from integrations.http import IntegrationError  # noqa: E402
from integrations import vault  # noqa: E402
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
    """The small slice of the feasibility assessment the UI shows right after it runs (and on reopen).
    It also carries the review history (earlier rounds of the check), so it survives a server restart and a
    reopen without a database schema change — it lives in the same `feasibility` JSON column."""
    c = ctx.get_contribution(AgentRole.FEASIBILITY_ASSESSMENT)
    if not c:
        return None
    o = c.output
    return {"verdict": o.get("verdict"), "rationale": o.get("verdict_rationale"), "confidence": o.get("confidence"),
            "counts": o.get("counts"), "headline_flaws": o.get("headline_flaws") or [],
            "recommended_changes": (o.get("recommended_changes") or [])[:3],
            # only the answers behind the critical/major flaws — the UI shows just these for editing
            "revisit": [{"question_id": r["question_id"], "severity": r["severity"], "reasons": r["reasons"][:3]}
                        for r in (o.get("questions_to_revisit") or [])],
            "unlinked": (o.get("unlinked_flaws") or [])[:4],
            # answers already reviewed in an earlier round (not offered for editing again) and the flaws that remain on them
            "reviewed": (o.get("reviewed_flaws") or [])[:6],
            "already_reviewed": [{"question_id": r["question_id"], "changed": r.get("changed", False)}
                                 for r in (o.get("already_reviewed") or [])],
            "round": o.get("review_round", 1),
            "history": ctx.feasibility_history,
            # answers to the pre-BRD clarifying questions ride along in the same JSON column (no schema change)
            "clarifications": ctx.clarifications,
            # serious flaws the person chose to keep (rethink.py) and how many still need a decision
            "accepted": ctx.accepted_flaws, "rethink": rt.counts(ctx),
            # what was pushed to Jira / Azure DevOps (ids and links only — credentials are never stored)
            "integrations": ctx.integration_links, "integration_settings": ctx.integration_settings}


def _feasibility_for_record(ctx, meta):
    """What is SAVED in the feasibility column: the browser-safe summary plus the encrypted token vault. The vault
    is added here (never in _feasibility_summary) and stripped again by _public_record before anything is sent out."""
    feas = _feasibility_summary(ctx) or ({**meta["feasibility"], "history": ctx.feasibility_history, "clarifications": ctx.clarifications,
                                          "accepted": ctx.accepted_flaws, "integrations": ctx.integration_links,
                                          "integration_settings": ctx.integration_settings} if meta.get("feasibility") else None)
    if ctx.integration_vault or ctx.integration_settings:
        feas = dict(feas or {})
        feas["integration_settings"] = ctx.integration_settings
        if ctx.integration_vault:
            feas["_vault"] = ctx.integration_vault
        else:
            feas.pop("_vault", None)
    return feas


def _public_record(rec: dict) -> dict:
    """A saved record safe to send to a browser: the encrypted token vault never leaves the server."""
    rec = dict(rec)
    if isinstance(rec.get("feasibility"), dict):
        rec["feasibility"] = {k: v for k, v in rec["feasibility"].items() if k != "_vault"}
    return rec


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
        # while a fresh run is between "cleared" and "feasibility done", keep the old summary but the CURRENT history
        "feasibility": _feasibility_for_record(ctx, meta),
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
    ctx.feasibility_history = list(((rec.get("feasibility") or {}).get("history")) or [])
    ctx.clarifications = list(((rec.get("feasibility") or {}).get("clarifications")) or [])
    ctx.accepted_flaws = list(((rec.get("feasibility") or {}).get("accepted")) or [])
    ctx.integration_links = dict(((rec.get("feasibility") or {}).get("integrations")) or {})
    ctx.integration_settings = dict(((rec.get("feasibility") or {}).get("integration_settings")) or {})
    ctx.integration_vault = (rec.get("feasibility") or {}).get("_vault") or None
    clar.seed_locked_decisions(ctx)
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
        clar.seed_locked_decisions(ctx)   # earlier answers to the clarifying questions stay settled decisions
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


# ---- Push user stories to Jira / Azure DevOps ---------------------------------------------------
# Credentials arrive in the request body, are used for that call (or the background push) and are never stored,
# logged or returned. Optional server-wide defaults come from environment variables (a token set there is used
# when the person leaves the token blank, and is never sent to the browser).
_ENV = {"jira": {"base_url": "JIRA_BASE_URL", "email": "JIRA_EMAIL", "project": "JIRA_PROJECT_KEY", "token": "JIRA_API_TOKEN"},
        "ado": {"base_url": "ADO_ORG_URL", "project": "ADO_PROJECT", "token": "ADO_PAT"}}


class _TicketExpired(Exception):
    pass


def _creds(project_id, target, body):
    """Connection details for one request. The token comes from (in order): an unlock ticket (a saved, decrypted token that
    stays on the server), what the person typed, or the server-wide default. Details are never logged."""
    body = body or {}
    given = body.get("creds") or {}
    c = {k: (str(given.get(k) or "").strip() or os.environ.get(env, "")) for k, env in _ENV[target].items() if k != "token"}
    typed = str(given.get("token") or "").strip()
    if body.get("ticket") and not typed:
        tok = vault.token_for(body["ticket"], project_id, target)
        if not tok:
            raise _TicketExpired()
        c["token"] = tok
    else:
        c["token"] = typed or os.environ.get(_ENV[target]["token"], "")
    return c


def _remember_settings(ctx, target, creds):
    """Each app project remembers its own board (site, email, project) — not the token."""
    s = {k: creds.get(k, "") for k in _ENV[target] if k != "token"}
    if ctx.integration_settings.get(target) != s:
        ctx.integration_settings[target] = s
        _persist(ctx)


def _integration_ctx(project_id, target):
    ctx = _get_ctx(project_id)
    if not ctx:
        return None, (jsonify({"error": "unknown project"}), 404)
    if target not in _ENV and target != "all":
        return None, (jsonify({"error": "unknown target"}), 404)
    return ctx, None


@app.route("/api/integrations/config", methods=["GET"])
def integrations_config():
    """Non-secret defaults to prefill the form, and whether a server-side token exists (so people need not paste one)."""
    out = {}
    for t, env in _ENV.items():
        out[t] = {k: os.environ.get(v, "") for k, v in env.items() if k != "token"}
        out[t]["token_configured"] = bool(os.environ.get(env["token"]))
    return jsonify(out)


@app.route("/api/project/<project_id>/integrations/state", methods=["GET"])
def integration_state(project_id):
    """This project's remembered board details and which tokens are saved (names only — never a token or ciphertext)."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    return jsonify({"settings": ctx.integration_settings, "saved_tokens": vault.targets(ctx.integration_vault),
                    "min_password": vault.MIN_PASSWORD})


def _vault_error(e):
    r = jsonify({"error": str(e), **({"retry_after": e.retry_after} if e.retry_after else {})})
    r.status_code = e.status
    if e.retry_after:
        r.headers["Retry-After"] = str(e.retry_after)
    return r


@app.route("/api/project/<project_id>/integrations/unlock", methods=["POST"])
def integration_unlock(project_id):
    """Password -> a short-lived ticket. The decrypted tokens stay in server memory; the browser only gets the ticket."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    try:
        tokens = vault.unlock(ctx.integration_vault, project_id, str((request.get_json(silent=True) or {}).get("password") or ""))
    except vault.VaultError as e:
        return _vault_error(e)
    return jsonify({"ticket": vault.issue_ticket(project_id, tokens), "targets": sorted(tokens), "expires_in": vault.TICKET_TTL})


@app.route("/api/project/<project_id>/integrations/lock", methods=["POST"])
def integration_lock(project_id):
    vault.revoke(ticket=(request.get_json(silent=True) or {}).get("ticket"))
    return jsonify({"locked": True})


@app.route("/api/project/<project_id>/integrations/<target>/token", methods=["POST"])
def integration_save_token(project_id, target):
    """Encrypt and save a token with the project's password (chosen now if this is the first one)."""
    ctx, err = _integration_ctx(project_id, target)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or "").strip()
    try:
        ctx.integration_vault = vault.save_token(ctx.integration_vault, project_id, str(body.get("password") or ""), target, token)
    except vault.VaultError as e:
        return _vault_error(e)
    vault.add_to_tickets(project_id, target, token)
    _persist(ctx)
    return jsonify({"saved": True, "saved_tokens": vault.targets(ctx.integration_vault)})


@app.route("/api/project/<project_id>/integrations/<target>/token", methods=["DELETE"])
def integration_forget_token(project_id, target):
    ctx, err = _integration_ctx(project_id, target)
    if err:
        return err
    ctx.integration_vault = vault.forget(ctx.integration_vault, None if target == "all" else target)
    vault.revoke(project_id=project_id, target=None if not ctx.integration_vault else target)
    _persist(ctx)
    return jsonify({"saved_tokens": vault.targets(ctx.integration_vault)})


@app.route("/api/project/<project_id>/integrations/<target>/check", methods=["POST"])
def integration_check(project_id, target):
    ctx, err = _integration_ctx(project_id, target)
    if err:
        return err
    try:
        creds = _creds(project_id, target, request.get_json(silent=True))
        out = backlog_sync.check(target, creds)
        _remember_settings(ctx, target, creds)
        return jsonify(out)
    except _TicketExpired:
        return jsonify({"error": "Your unlock has expired — enter your password again.", "expired": True}), 401
    except IntegrationError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/project/<project_id>/integrations/<target>/preview", methods=["POST"])
def integration_preview(project_id, target):
    ctx, err = _integration_ctx(project_id, target)
    if err:
        return err
    try:
        c = _creds(project_id, target, request.get_json(silent=True))
    except _TicketExpired:
        c = {}
    return jsonify(backlog_sync.preview(ctx, target, c if c.get("token") else None))


@app.route("/api/project/<project_id>/integrations/<target>/push", methods=["POST"])
def integration_push(project_id, target):
    ctx, err = _integration_ctx(project_id, target)
    if err:
        return err
    if jobs.is_running(project_id):
        return jsonify({"error": "The AI agents are still running — push once they have finished."}), 409
    body = request.get_json(silent=True) or {}
    try:
        creds = _creds(project_id, target, body)
    except _TicketExpired:
        return jsonify({"error": "Your unlock has expired — enter your password again.", "expired": True}), 401
    _remember_settings(ctx, target, creds)
    job_id = backlog_sync.start_push(project_id, ctx, target, creds, body.get("options") or {}, lambda: _persist(ctx))
    return jsonify({"push_id": job_id})   # NOT "job_id": the front-end api() helper polls that name as an agent job


@app.route("/api/project/<project_id>/integrations/push/<job_id>", methods=["GET"])
def integration_push_status(project_id, job_id):
    st = backlog_sync.job_status(project_id, job_id)
    return (jsonify(st) if st else (jsonify({"error": "unknown job"}), 404))


@app.route("/api/project/<project_id>/feasibility/rethink", methods=["GET"])
def get_rethink(project_id):
    """Every serious flaw with a recommended fix and a proposed answer for each answer behind it."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    return jsonify({"flaws": rt.plan(ctx), "counts": rt.counts(ctx)})


@app.route("/api/project/<project_id>/feasibility/rethink", methods=["POST"])
def post_rethink(project_id):
    """{changes: {question id: new answer}, accept: [flaw keys], reopen: [flaw keys]} — fix some flaws, knowingly accept others."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if jobs.is_running(project_id):
        return jsonify({"error": "The AI agents are running — wait for the current step to finish."}), 409
    body = request.get_json(silent=True) or {}
    result = rt.apply(ctx, body.get("changes") or {}, body.get("accept") or [], body.get("reopen") or [])
    _persist(ctx)
    return jsonify({**result, "counts": rt.counts(ctx), "questions": _question_dicts(ctx)})


@app.route("/api/project/<project_id>/clarifications", methods=["GET"])
def get_clarifications(project_id):
    """Questions still open before the BRD is written — asked in a popup, never listed in the BRD."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    items = clar.pending_questions(ctx)
    return jsonify({"questions": items, "suggestions": clar.suggest(ctx, items) if items else {}})


@app.route("/api/project/<project_id>/clarifications/suggest", methods=["POST"])
def suggest_clarifications(project_id):
    """Fresh AI recommendations given what is currently selected in the popup ({draft: {item id: answer}}),
    so changing one answer updates the recommendations that depend on it."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    draft = (request.get_json(silent=True) or {}).get("draft") or {}
    items = clar.pending_questions(ctx)
    return jsonify({"suggestions": clar.suggest(ctx, items, draft) if items else {}})


@app.route("/api/project/<project_id>/clarifications", methods=["POST"])
def post_clarifications(project_id):
    """Saves the answers ([{id, answer}]; an empty answer = skip, use the planning default)."""
    ctx = _get_ctx(project_id)
    if not ctx:
        return jsonify({"error": "unknown project"}), 404
    if jobs.is_running(project_id):
        return jsonify({"error": "The AI agents are running — wait for the current step to finish."}), 409
    body = request.get_json(silent=True) or {}
    result = clar.apply_answers(ctx, body.get("answers") or [])
    _persist(ctx)
    return jsonify({**result, "questions": _question_dicts(ctx)})


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


def _heal_artefacts(rec: dict) -> list:
    """Documents generated by older versions carried the business idea cut off at 60 characters
    ("Project: An app to match resume with skills & present them on the das"). Restore the full
    idea in those saved documents when they are opened, so nobody has to regenerate them."""
    arts = rec.get("artefacts") or []
    idea = " ".join((rec.get("business_idea") or "").split())
    cut = idea[:60]
    if len(idea) <= 60 or not cut:
        return arts
    healed = []
    for a in arts:
        a = dict(a)
        md = a.get("content_markdown") or ""
        md = md.replace(f"**Project:** {cut}\n", f"**Project:** {idea}\n", 1)
        title = a.get("title") or ""
        if title.endswith(f"— {cut}"):
            title = title[: -len(cut)] + idea
        a["content_markdown"], a["title"] = md, title
        healed.append(a)
    return healed


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
        "artefacts": _heal_artefacts(rec),
    })


@app.route("/api/project/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    """Deletes a project (unfinished draft OR completed package). Refused while the AI agents
    are still running for it, so a background job can never re-save a deleted project."""
    rec = get_project_store().get(project_id)
    if not rec:
        return jsonify({"error": "project not found"}), 404
    if jobs.is_running(project_id):
        return jsonify({"error": "The AI agents are still running for this project. Try again once they finish."}), 409
    get_project_store().delete(project_id)
    PROJECTS.pop(project_id, None)
    META.pop(project_id, None)
    return jsonify({"deleted": project_id})


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
    record = _public_record(dict(record, artefacts=_heal_artefacts(record)))
    return jsonify(record)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("\n  AI Product Specification Package — local demo server")
    print(f"  Running in {'LIVE' if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('GEMINI_API_KEY') else 'MOCK'} mode")
    print(f"  Open: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

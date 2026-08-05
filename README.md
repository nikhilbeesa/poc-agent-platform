# AI Product Engineering Agent Platform — POC

A working proof of concept for the multi-agent platform described in the
POC spec: capture a business idea, run guided discovery, hand it to a team
of specialist AI agents, and export consistent, implementation-ready
artefacts. All 5 phases below are complete.

## What's here

```
poc-agent-platform/
├── README.md
├── requirements.txt
├── webapp/                              # Local web demo (Flask + schematic UI)
│   ├── server.py
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
├── artefact_templates/                 # Markdown templates for the 3 deliverables
│   ├── business_requirements.md
│   ├── user_stories.md
│   └── architecture_recommendation.md
└── src/
    ├── context.py                      # Shared "notebook" every agent reads/writes
    ├── logging_config.py               # Structured logging for every agent call
    ├── llm_client.py                   # Shared live/mock LLM call helper
    ├── discovery.py                    # Phase 2: idea intake, classification, questions
    ├── orchestrator.py                 # Phase 3: sequences the 5 agents
    ├── export.py                       # Phase 5: fills agent output into templates
    ├── demo.py                         # Narrated live-demo script for presenting this
    ├── test_discovery_samples.py       # Phase 2 test across 4 sample ideas
    ├── test_end_to_end.py              # Phase 5 test + success criteria validation
    ├── agents/                         # Phase 3: the 5 specialist agents
    │   ├── base.py                     #   shared contract every agent follows
    │   ├── business_analyst.py
    │   ├── product_manager.py
    │   ├── solution_architect.py
    │   ├── security.py
    │   └── qa_reviewer.py
    └── knowledge/                      # Phase 4: the Product Knowledge Engine
        ├── store.py                    #   persisted, file-backed domain storage
        ├── bootstrap_seed_data.py      #   seeds the 3 starter domains
        ├── learn.py                    #   learns + persists new domains automatically
        └── data/domains/*.json         #   created on first run
```

## Web demo (local, no API key needed)

A real local web app — Flask backend + a schematic-style frontend showing
the pipeline running live: discovery questions, all 5 agents lighting up
one by one on a wiring diagram, and the exported documents in a tabbed
viewer.

```bash
pip install flask
python3 webapp/server.py
```

Then open **http://localhost:5001**. Runs entirely in mock mode — no
`ANTHROPIC_API_KEY` needed. Type an idea (or click one of the example
chips), answer the discovery questions, watch the agents run, then export
and read the generated documents. Try the "unseen domain" example chip to
see the knowledge engine learn a new domain live, with a banner calling it
out.

`webapp/server.py` is a thin API layer over the exact same pipeline code
used everywhere else (`discovery.py`, `orchestrator.py`'s `AGENT_PIPELINE`,
`export.py`) — nothing was duplicated or reimplemented for the UI.

## Demo it (terminal version)

```bash
python3 src/demo.py                                          # quick run, auto-answered
python3 src/demo.py --interactive                             # you answer the questions live
python3 src/demo.py --idea "your business idea here"           # custom idea
python3 src/demo.py --interactive --idea "your idea here"      # both
```

Narrated, presentation-friendly walkthrough — clean phase headers, live
per-agent timing, and a preview of the exported documents. Good demo
structure:

1. Run once with a common idea (e-commerce, booking app) to show the
   normal path.
2. Run again with something the system has never seen (a pet-sitting app,
   a tutoring platform, anything odd) to show it **learning a new domain
   live** — this is the most convincing moment to show.
3. Run that same unusual idea a *third* time to show it reusing the
   learned domain instead of re-learning it.
4. Close with `test_end_to_end.py`'s success-criteria table (below) on
   screen as the "we validated this against the spec" moment.

## Deploying to production (Render + Supabase, single host)

Architecture: **one Render service serves everything** — Flask already
serves both the frontend (`webapp/static/`) and the `/api/*` routes from
the same app, so there's no separate frontend host, no CORS, no proxy
config needed. **Domain knowledge lives in Supabase Postgres** instead of
local JSON files, so it persists centrally rather than on one server's
disk (which free-tier hosts don't reliably persist across deploys anyway).

Netlify isn't used here — Netlify's serverless functions are Node/TS-
first, and splitting frontend/backend across two hosts added complexity
with no real benefit once you factor in that Flask already serves static
files itself. (If you specifically want Netlify's CDN later, the old
split-host approach still works — ask and I'll bring it back — but this
is the simpler default.)

### 1. Choose your LLM provider

Two supported out of the box, switched with one env var — nothing else
in the code changes:

| `LLM_PROVIDER` | Required key | Notes |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com) | Trial credit for new accounts, then pay-per-token |
| `gemini` | `GEMINI_API_KEY` from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Actual ongoing free tier (Flash/Flash-Lite models, rate-limited) — no credit card needed |

Free-tier model availability shifts fairly often on Google's side —
`GEMINI_MODEL` defaults to `gemini-2.5-flash`; check
[ai.google.dev/pricing](https://ai.google.dev/pricing) if that stops
working and override it via env var.

### 2. Set up Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. **SQL Editor → New Query** → paste in `deploy/supabase_schema.sql` →
   Run. Creates the `domains` table and seeds the 3 starter domains.
3. **Settings → API** → note your **Project URL** and **anon/service key**.

### 3. Deploy to Render

1. Push this repo to GitHub.
2. On [render.com](https://render.com): **New → Web Service** → connect
   your repo. It reads `render.yaml` automatically, or set manually:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn wsgi:app`
3. Add environment variables (**Settings → Environment**):
   - `LLM_PROVIDER` — `anthropic` or `gemini` (defaults to `anthropic` if unset)
   - `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` — whichever matches your provider choice
   - `SUPABASE_URL`, `SUPABASE_KEY` — from Supabase Settings → API
4. Deploy. Render gives you one URL serving the whole app —
   `https://poc-agent-platform.onrender.com` — open it, done.

   Note: Render's free tier spins down after inactivity — the first
   request after a while takes ~30-60s to wake back up. Normal, not a bug.

### What's different in production vs. local mock mode

- **Discovery questions are genuinely dynamic.** In mock mode, questions
  come from a fixed per-domain checklist. With a real API key (either
  provider), the full question set is generated fresh per idea — two
  different booking-app ideas get noticeably different questions, not
  the same 5 every time.
- **Domain knowledge lives in Supabase**, not local JSON files — anyone
  using the deployed app contributes to and benefits from the same
  growing knowledge base.
- Everything else (agents, orchestration, export, QA consistency check)
  works identically — those were already provider-agnostic.

## Try it (full test suite)

```bash
pip install -r requirements.txt

python3 src/context.py                  # smoke-test the shared context schema
python3 src/logging_config.py           # smoke-test logging
python3 src/discovery.py                # run discovery on one sample idea
python3 src/test_discovery_samples.py   # run discovery on 4 sample ideas
python3 src/orchestrator.py             # run the full 5-agent pipeline on one idea
python3 src/knowledge/bootstrap_seed_data.py   # (re)seed the 3 starter domains
python3 src/knowledge/learn.py          # demo: learn a new domain from an unmatched idea
python3 src/export.py                   # export one idea's artefacts to /tmp/poc_export_test
python3 src/test_end_to_end.py          # full pipeline across 4 ideas + success criteria check
```

Runs in **mock mode** by default (deterministic stand-ins for every AI
call, so the pipeline can be built/tested without API access). Set
`ANTHROPIC_API_KEY` to switch every AI step to the real Claude API —
no code changes needed anywhere.

```bash
export ANTHROPIC_API_KEY=your_key_here
python3 src/test_end_to_end.py
```

## Phase 1 — Foundation & Design

- **Stack:** Python, `anthropic` SDK, `pydantic` for the shared schema.
  Not locked in — the spec explicitly avoids prescribing a fixed stack.
- **Shared project context (`context.py`):** a single `ProjectContext`
  object every agent reads from and writes to — no agent talks to another
  agent directly. Tracks: raw idea, domain, discovery Q&A, each agent's
  contribution (kept separate so QA can compare them), consistency notes,
  and final artefacts.
- **Artefact templates:** Markdown templates for the 3 named deliverables.
- **Logging:** every agent call writes a structured JSON line to
  `logs/agent_activity.log` for observability/auditability.

## Phase 2 — Discovery Engine

- **`discovery.py`:** intake (deterministic) → domain classification (AI)
  → dynamic follow-up questions (AI, seeded from known-domain baselines).
- **Live vs. mock:** falls back to keyword-matching heuristics with no
  API key; identical interface either way.
- Tested against 4 sample ideas spanning 3 known domains plus 1 unseen one.

## Phase 3 — AI Agent Team

All 5 roles from spec Section 6, sharing one contract (`agents/base.py`):
read context → produce structured output → log → append as a contribution.

- **Business Analyst** — requirements, goals, constraints, assumptions
- **Product Manager** — reads BA's output; epics, user stories, priorities
- **Solution Architect** — reads BA's output; recommended approach +
  alternatives (recommends, doesn't assume a fixed stack)
- **Security** — reads BA + Architect's output; risks grounded in the
  actual proposed components
- **QA / Review** — reads everyone; checks for contradictions, writes to
  `context.consistency_notes`, flags overall readiness

`orchestrator.py` sequences all 5 in dependency order and blocks the
pipeline if discovery isn't complete. Verified: real handoffs (Architect
quotes BA's actual requirements back), 5/5 contributions, 0 conflicts.

## Phase 4 — Knowledge Engine

- **`knowledge/store.py`:** persisted, file-backed domain storage
  (`KnowledgeStore`) replacing the earlier hardcoded dict.
- **`knowledge/bootstrap_seed_data.py`:** seeds 3 starter domains
  (booking platform, e-commerce, marketplace), idempotent.
- **`knowledge/learn.py`:** when discovery hits an idea that doesn't match
  any known domain, this analyses it and **persists a new domain entry**
  automatically — Section 7 of the spec verbatim: unknown domains get
  "analysed and incorporated without changing the platform architecture."
- Verified: an unrecognised farm-management idea was auto-learned as a new
  `small_farms` domain; re-running the same idea reused it instead of
  re-learning (~1ms, no duplicate file).

## Phase 5 — Output, Review & Testing

- **`export.py`:** fills agent outputs into the Markdown templates,
  producing the 3 Phase 1 deliverables. Combines Architect + Security
  findings into one coherent security section.
- **`test_end_to_end.py`:** runs the complete pipeline across 4 sample
  ideas and checks all 5 success criteria from spec Section 12:

  | # | Success criterion | Result |
  |---|---|---|
  | 1 | User can complete guided discovery | **PASS** — 4/4 ideas |
  | 2 | Multiple AI agents collaborate | **PASS** — 5/5 agents every run, handoffs verified |
  | 3 | Artefacts are internally consistent | **PASS** — 4/4 runs QA "ready", 0 conflicts |
  | 4 | Architecture adapts across domains | **PASS** — 4 distinct domains, 1 auto-learned mid-test |
  | 5 | Solid foundation for Phase 2 | **PASS** (qualitative) |

### Known limitations — read before treating this as validated

- **Everything above ran in mock mode.** No API key was set in the build
  environment, so every "AI" step used deterministic stand-ins, not real
  reasoning. Mock output is occasionally grammatically awkward (e.g. "a
  small farms") — a real LLM call wouldn't produce that.
  **Recommended next step: set `ANTHROPIC_API_KEY` and re-run
  `test_end_to_end.py` against real model output before trusting these
  results as representative of live quality.**
- The end-to-end test's discovery answers are auto-generated placeholders,
  not real user input.
- QA's "ready" status means *internal consistency between agents*, not
  that a human has reviewed the business plan for soundness.

## Status: all 5 phases complete

Phase 1 deliverables (spec Section 10) are all present: end-to-end flow,
configurable orchestration (`AGENT_PIPELINE` in `orchestrator.py`),
knowledge engine prototype, representative artefacts, and clear extension
points — new agents, new domains, and mock→live mode all require zero
architecture changes.

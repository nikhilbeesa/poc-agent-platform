# AI Product Engineering Agent Platform — POC

A working proof of concept: capture a business idea, run guided discovery,
hand it to a team of 7 specialist AI agents, and export 7 detailed,
implementation-ready documents. Runs locally in mock mode with zero setup,
or live against Anthropic Claude or Google Gemini.

## What's here

```
poc-agent-platform/
├── README.md
├── requirements.txt
├── wsgi.py                              # Render entry point
├── render.yaml                          # Render deployment blueprint
├── deploy/
│   └── supabase_schema.sql              # DB schema (domains + projects tables)
├── artefact_templates/                  # Markdown templates for the 7 documents
│   ├── business_requirements.md
│   ├── user_stories.md
│   ├── prd.md
│   ├── architecture_recommendation.md
│   ├── security_assessment.md
│   ├── qa_test_strategy.md
│   └── ai_review_report.md
├── webapp/                              # Local/hosted web demo (Flask + schematic UI)
│   ├── server.py
│   └── static/
│       ├── index.html
│       ├── style.css
│       └── app.js
└── src/
    ├── context.py                       # Shared "notebook" every agent reads/writes
    ├── logging_config.py                # Structured logging for every agent call
    ├── llm_client.py                    # Provider-agnostic LLM wrapper (Anthropic/Gemini) + retries
    ├── discovery.py                     # Idea intake, domain classification, dynamic questions
    ├── orchestrator.py                  # Sequences the 7 agents
    ├── export.py                        # Fills agent output into the 7 templates
    ├── project_store.py                 # Persists completed projects (History dashboard)
    ├── demo.py                          # Narrated terminal demo script
    ├── test_discovery_samples.py
    ├── test_end_to_end.py               # Full pipeline test + success-criteria validation
    ├── agents/
    │   ├── base.py                      # Shared contract every agent follows
    │   ├── business_analyst.py          # -> Business Requirements Document
    │   ├── product_manager.py           # -> User Stories Document
    │   ├── product_requirements.py      # -> Product Requirements Document (PRD)
    │   ├── solution_architect.py        # -> Solution Architecture Recommendation
    │   ├── security.py                  # -> Security Assessment
    │   ├── qa_test_strategy.py          # -> QA / Test Strategy
    │   └── qa_reviewer.py               # -> AI Review Report (final consistency check)
    └── knowledge/
        ├── store.py                     # Persisted, file- or Supabase-backed domain storage
        ├── bootstrap_seed_data.py       # Seeds the 3 starter domains
        └── learn.py                     # Learns + persists new domains automatically
```

## Web demo (local, no API key needed)

```bash
pip install -r requirements.txt
python3 webapp/server.py
```

Open **http://localhost:5001**. Dashboard-first UI: a table of past
projects, "+ New project" opens the intake flow. Runs entirely in mock
mode by default.

## Terminal demo

```bash
python3 src/demo.py --interactive
python3 src/demo.py --idea "your business idea here"
```

## Full test suite

```bash
python3 src/context.py
python3 src/logging_config.py
python3 src/discovery.py
python3 src/test_discovery_samples.py
python3 src/orchestrator.py
python3 src/export.py
python3 src/test_end_to_end.py          # full pipeline across 4 ideas + success-criteria check
```

## The 7 agents -> 7 documents

| # | Agent | Document | Depends on |
|---|---|---|---|
| 1 | Business Analyst | Business Requirements Document | — (runs first) |
| 2 | Product Manager | User Stories Document | Business Analyst |
| 3 | Product Requirements | Product Requirements Document (PRD) | Business Analyst + Product Manager |
| 4 | Solution Architect | Solution Architecture Recommendation | Business Analyst + PRD |
| 5 | Security | Security Assessment | Business Analyst + Architect |
| 6 | QA Test Strategy | QA / Test Strategy | Product Manager + Security |
| 7 | AI Reviewer | AI Review Report | Everyone (runs last) |

Each agent has its own file under `src/agents/`, follows the same
contract (`agents/base.py`), and runs in both live mode (real LLM calls)
and mock mode (deterministic fallback, no API key needed).

## LLM provider — Anthropic or Gemini

Switched with one env var, no code changes:

| `LLM_PROVIDER` | Required key | Notes |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | Trial credit for new accounts, then pay-per-token |
| `gemini` | `GEMINI_API_KEY` | Actual ongoing free tier — no credit card needed |

`GEMINI_MODEL` defaults to `gemini-3.1-flash-lite` (~1,500 requests/day
free). Free-tier model names/quotas shift often on Google's side — check
https://ai.google.dev/gemini-api/docs/rate-limits if the default stops
working, and override via env var rather than waiting for a code update.

Every LLM call automatically retries transient errors (429/503/etc.) up
to 3 times with backoff before surfacing a real error — see
`src/llm_client.py`.

## Deploying to production (Render + Supabase, single host)

One Render service serves everything — Flask serves both the frontend
and the `/api/*` routes from the same app, so there's no separate
frontend host, no CORS.

1. **Supabase**: create a project at supabase.com → SQL Editor → paste
   & run `deploy/supabase_schema.sql` → note your Project URL + anon key
   from Settings → API.
2. **Render**: New → Web Service → connect your repo (reads
   `render.yaml` automatically, or set Build Command
   `pip install -r requirements.txt` / Start Command
   `gunicorn wsgi:app --timeout 120` manually). Add env vars:
   `LLM_PROVIDER`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`,
   `SUPABASE_URL`, `SUPABASE_KEY`.
3. Deploy — Render gives you one URL serving the whole app.

Render's free tier spins down after inactivity — first request after a
while takes ~30-60s to wake up. Normal, not a bug.

## Known limitations

- Mock mode output is deterministic and occasionally grammatically
  awkward — it proves the pipeline works, not the quality of real AI
  reasoning. Set an API key to see genuinely tailored output.
- Discovery questions are only genuinely dynamic in live mode; mock mode
  uses a fixed per-domain checklist since there's no real reasoning
  available offline.
- QA's "ready" verdict means *internal consistency between agents*, not
  that a human has reviewed the business plan for soundness.

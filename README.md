# AI Product Specification Package — POC

A working proof of concept: capture a business idea, run guided discovery,
hand it to 5 specialist AI agents, and export a **5-document Product
Specification Package** — ready to hand off to an independent, external
Design AI Agent that generates UI/UX designs from these documents alone.

## Scope

This POC's responsibility ends at producing a complete, detailed,
structured, internally consistent, AI-consumable specification package.
It does **not** build the downstream Design AI Agent, generate UI
designs, wireframes, or any frontend code.

## What's here

```
poc-agent-platform/
├── README.md
├── requirements.txt
├── wsgi.py                              # Render entry point
├── render.yaml                          # Render deployment blueprint
├── deploy/
│   └── supabase_schema.sql              # DB schema (domains + projects tables)
├── artefact_templates/                  # Markdown templates for the 5 documents
│   ├── business_requirements.md
│   ├── user_stories.md
│   ├── prd.md
│   ├── ux_product_flow_specification.md
│   └── ai_handoff_validation.md
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
    ├── orchestrator.py                  # Sequences the 5 agents
    ├── export.py                        # Fills agent output into the 5 templates
    ├── project_store.py                 # Persists completed packages (Dashboard/History)
    ├── demo.py                          # Narrated terminal demo script
    ├── test_discovery_samples.py
    ├── test_end_to_end.py               # Full pipeline test + acceptance criteria check
    ├── agents/
    │   ├── base.py                      # Shared contract every agent follows
    │   ├── business_analyst.py          # -> Business Requirements Document
    │   ├── product_manager.py           # -> User Stories Document
    │   ├── product_requirements.py      # -> PRD (absorbs architecture + security context)
    │   ├── ux_product_flow.py           # -> UX / Product Flow Specification
    │   └── ai_handoff_validation.py     # -> AI Handoff Validation Report (final agent)
    └── knowledge/
        ├── store.py                     # Persisted, file- or Supabase-backed domain storage
        ├── bootstrap_seed_data.py       # Seeds the 3 starter domains
        └── learn.py                     # Learns + persists new domains automatically
```

## The 5 agents → 5 documents

| # | Agent | Document | Answers | Depends on |
|---|---|---|---|---|
| 1 | Business Analyst | `business_requirements.md` | Why are we building this? | — (runs first) |
| 2 | Product Manager | `user_stories.md` | Who needs to do what, and why? | Business Analyst |
| 3 | Product Requirements | `prd.md` | What should the product do? | Business Analyst + Product Manager |
| 4 | UX / Product Flow | `ux_product_flow_specification.md` | How should users experience it? | Product Manager + PRD |
| 5 | AI Handoff Validation | `ai_handoff_validation.md` | Is the package ready to hand off? | All 4 — runs last |

**No separate Architecture, Security, or QA Test Strategy documents are
generated.** Architecture and security context that affects product
behavior is absorbed into the PRD as dedicated sections (`Technical &
Integration Constraints`, `Security, Privacy & Access Constraints`) —
scoped to what a UI/UX designer actually needs, not infrastructure
implementation detail.

## Traceability

Every document uses consistent, cross-referenced IDs so a downstream
agent (or a human) can trace exactly where a screen or flow originated:

```
BR-001 (business requirement)
  ↓
US-001 (user story)
  ↓
FR-001 (PRD functional requirement)
  ↓
FLOW-001 / SCR-001 (UX flow / screen)
```

The AI Handoff Validation agent checks this traceability explicitly —
e.g. it flags a business requirement with no corresponding user story, or
a functional requirement with no corresponding screen.

## Web demo (local, no API key needed)

```bash
pip install -r requirements.txt
python3 webapp/server.py
```

Open **http://localhost:5001**. Dashboard-first UI: a table of past
projects with their handoff status, "+ New project" opens the intake
flow. Runs entirely in mock mode by default.

## Terminal demo

```bash
python3 src/demo.py --interactive
python3 src/demo.py --idea "your business idea here"
```

## Full test suite

```bash
python3 src/context.py
python3 src/discovery.py
python3 src/test_discovery_samples.py
python3 src/orchestrator.py
python3 src/export.py
python3 src/test_end_to_end.py          # full pipeline across 4 ideas + acceptance criteria check
```

## LLM provider — Anthropic or Gemini

Switched with one env var, no code changes:

| `LLM_PROVIDER` | Required key | Notes |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | Trial credit for new accounts, then pay-per-token |
| `gemini` | `GEMINI_API_KEY` | Actual ongoing free tier — no credit card needed |

`GEMINI_MODEL` defaults to `gemini-3.1-flash-lite` (~1,500 requests/day
free). Free-tier model names/quotas shift often on Google's side — check
https://ai.google.dev/gemini-api/docs/rate-limits if the default stops
working, and override via env var.

Every LLM call automatically retries transient errors (429/503/etc.) up
to 3 times with backoff — see `src/llm_client.py`.

## Deploying to production (Render + Supabase, single host)

1. **Supabase**: create a project → SQL Editor → paste & run
   `deploy/supabase_schema.sql` → note your Project URL + anon key from
   Settings → API.
2. **Render**: New → Web Service → connect your repo (reads
   `render.yaml` automatically, or set Build Command
   `pip install -r requirements.txt` / Start Command
   `gunicorn wsgi:app --timeout 120` manually). Add env vars:
   `LLM_PROVIDER`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`,
   `SUPABASE_URL`, `SUPABASE_KEY`.
3. Deploy — Render gives you one URL serving the whole app.

## AI Handoff Validation — the final quality gate

The last agent produces exactly one of three statuses, and does **not**
default to "ready":

- **READY FOR DESIGN AGENT** — no gaps or conflicts found
- **READY WITH WARNINGS** — minor gaps/conflicts found, package is usable but imperfect
- **NOT READY FOR DESIGN AGENT** — a required document is missing entirely, or too many gaps/conflicts exist

Verified in testing: deliberately running the pipeline with the UX
document missing correctly forces `NOT READY FOR DESIGN AGENT` — the
status logic isn't cosmetic.

## Known limitations

- Mock mode output is deterministic and occasionally grammatically
  awkward — it proves the pipeline works, not the quality of real AI
  reasoning. Set an API key to see genuinely tailored output.
- Discovery questions are only genuinely dynamic in live mode; mock mode
  uses a fixed per-domain checklist since there's no real reasoning
  available offline.
- The AI Handoff Validation's cross-document consistency checks in mock
  mode use a handful of genuinely-checkable rules (e.g. ID cross-
  referencing, role alignment) as a stand-in for the LLM's broader
  judgment in live mode.

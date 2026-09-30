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
│       ├── export.js                    # Client-side Word (.docx) + ZIP export (no library, no server)
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

## Workflow & document updates (v3)

**Drafts, resume and full-process history**
- Every project is saved from the moment discovery starts, and again after every answer or skip. Closing the tab never loses work: the dashboard shows the project as a `DRAFT · n/m answered` row with **Resume →** (and **Discard**), and it reopens on the first unanswered question. The URL carries `#project=<id>`, so a refresh or "reopen closed tab" also resumes it.
- The typed business idea is kept locally until discovery is run.
- Opening a finished project restores the *whole* process — the idea, every question with its answer, the agent run, and the five documents. Use **Edit** on any answer, then **Re-run AI Agents**; the previous package stays saved until the new one replaces it.
- If the server restarts mid-session, the project is rebuilt from its saved record.
- **Supabase users must run the new block at the bottom of `deploy/supabase_schema.sql`** (adds `status`, `questions`, `agent_log`, `updated_at`; idempotent).

**Run / resolve controls**
- **Run AI Agents** disables itself the instant it is clicked (and the server also refuses a second concurrent run). It re-enables only if an agent fails, as **Retry AI Agents**, which continues from the agent that failed instead of starting over.
- **Resolve issues** is shown only after the automatic resolution rounds have finished and issues still remain.
- **Download all** produces a single `.zip` (built in the browser, no extra library).

**Discovery**
- The questionnaire always ends with an optional free-text question asking for any additional information the generated questions may not have covered. It is passed to every agent like any other answer.

**Documents**
- *Process-flow diagrams* follow flowchart notation: one rounded Start and one or more End terminators, rectangles for steps, diamonds for decisions with labelled Yes/No branches, single-direction arrows with right-angle connectors, and colour-coded node types. Each diagram sits on its own light canvas card with a legend. Live-mode prompts require this notation and `chunked.standardize_mermaid` applies the styling to every diagram, including model-written ones.
- *Data validation* in each user story is a table: **Field · Field type · Mandatory / Optional · Validation rule**. Legacy `"Field: rule"` strings are converted (type and mandatory inferred) by `chunked.normalize_validation_rules`.
- *Definition of Ready* and *Definition of Done* are now generated **inside each user story**, built from that story's own dependencies, fields, messages and acceptance criteria. The former shared sections were removed (the document now has 13 sections).
- The document viewer uses the full available width; tables scroll inside their own wrapper instead of squeezing or overflowing.

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

## Document depth (v2)

Generated documents now include, by design:

- **User stories:** per-story *Data validation*, *Error messages*, *Empty states* and *Edge cases* sections, plus 5–6 acceptance criteria covering them.
- **Business Requirements:** Mermaid *envisioned flow diagrams* (section 13), a ranked *risk register* with likelihood, severity, derived rating, owner and trigger (section 33), and *key business parameters* (section 18) — undecided values appear as "TBD" and are also listed under Open Questions.
- **AI Handoff Validation** checks for these and reports what is missing (live mode).

Cost note: live runs make roughly 4 extra requests (smaller story batches plus one extra BRD call). Tunable with `LLM_MAX_RPM` / `LLM_MAX_PARALLEL`.

## Recent changes (workflow & document upgrades)

**Documents**
- **Process-flow diagrams** follow standard flowchart notation: rounded Start/End terminators, rectangular process steps, diamond decisions with every branch labelled (Yes/No), single-direction arrows and right-angle connector lines. Each diagram sits on its own light canvas card with a notation legend, and node types are colour-coded. Because Mermaid clips connectors to a diamond's slanted edge, the viewer re-routes every connector after rendering (`routeFlowchart` in `app.js`): lines leave a decision from its left/right/bottom corner point, run at right angles, enter the target's top centre (or side, for retry loops), and the arrow tip lands on the shape border. An edge that cannot be routed without crossing a shape keeps Mermaid's own line. The Agent Assembly Line keeps the dark theme. (`chunked.standardize_mermaid` for the node styling.)
- **Data validation** in every user story is a table: *Field | Field type | Mandatory / Optional | Validation rule*. The live Product Manager agent is asked for structured objects; legacy `"Field: rule"` strings are normalised so type and mandatory/optional are never blank (`chunked.normalize_validation_rules`).
- **Definition of Ready / Done** is written **per story** (built from that story's own dependencies, fields, messages and acceptance criteria) instead of once for the whole backlog. The two global sections were removed from the template.
- Document viewer uses the **full available width** for text and tables (tables scroll inside their own wrapper).
- **Download all** produces a single `.zip` (client-side, no extra library).

**Discovery & workflow**
- A final optional free-text question — *"any additional information or data…?"* — is always appended (`discovery.ADDITIONAL_INFO_QUESTION_ID`).
- **Run AI Agents** locks on the first click; it re-enables only if an agent fails and then reads *Retry AI Agents* and resumes from the failed agent.
- **Resolve issues** appears only after the automatic resolution rounds have finished and issues still remain.
- **Drafts:** the project is saved on creation and after every answer/skip. Closing the tab loses nothing — the URL carries `#project=<id>`, and the dashboard shows *DRAFT · n/m answered* with **Resume** and **Discard**. The idea text is also kept locally until discovery starts.
- **Reopening a finished project** shows the whole process — idea, every question with its answer (editable), the agent run and the documents. Edit answers and use **Re-run AI Agents**; the previous package stays in storage until the new one replaces it.

**API additions:** `GET /api/project/<id>/session` (reopen/resume), `DELETE /api/project/<id>` (discard unfinished drafts only).

**Database:** re-run `deploy/supabase_schema.sql` (idempotent) to add `status`, `questions`, `agent_log` and `updated_at` to `projects`. Local-file storage needs no migration. Projects saved before this version still open (documents only — their questions were never recorded).


## Downloading the documents as Word files

Sheet 04 offers each document as a Word file (`.docx`) or as the original Markdown:

- **Download this document (Word .docx)** — the document shown in the viewer.
- **Download all 5 (Word .docx, zipped)** — one `.zip` with five `.docx` files.
- **.md / All 5 .md (.zip)** — the original Markdown, unchanged.

The conversion runs entirely in the browser (`webapp/static/export.js`) — there is no server
round-trip and no extra dependency. Headings, lists, bold/italic/code, links and tables are
converted to native Word styles; tables with 7+ columns get their own landscape page; Mermaid
process-flow diagrams are embedded as images (if a diagram can't be drawn, its source text is
included instead so an export never fails). Files open in Word, LibreOffice and Google Docs.

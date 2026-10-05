# CompanyOps AI

An autonomous enterprise AI operator that runs a mock company ERP through browser automation and APIs.

Built as an engineering hiring assignment. The point is to show a **controlled, observable agent loop** that we write and understand ourselves, with no agent frameworks (no LangChain, LangGraph, CrewAI, AutoGen, etc.).

```
Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Complete
```

## Status

**Done:** project skeleton (FastAPI `/health`) and **MiniERP**, the mock ERP the agent will operate. There is no agent, no LLM integration, and no frontend yet.

## Project layout

```
backend/app/
  main.py          FastAPI entrypoint
  agent/           Agent loop, structured agent state, planner
  tools/           Tools the agent can call (browser, ERP API, ...)
  policy/          Policy / permission engine and human approval gates
  recovery/        Failure handling, retries, replanning
  verification/    Independent verification of results
  memory/          Company memory
  database/        Persistence (runs, audit log, memory)
  api/             FastAPI routes
  workers/         Redis/ARQ background execution
erp/               MiniERP: the mock company ERP (Flask + SQLite)
data/              Source documents (e.g. invoice_acme.txt) and local databases (*.db git-ignored)
tests/             Pytest tests
runs/              Per-run output: evidence, logs (contents git-ignored)
```

## Planned architecture

| Stage | Responsibility | Lives in |
|---|---|---|
| **Goal / Understand** | Accept a goal, pull relevant company memory, restate it as a structured task | `agent/`, `memory/` |
| **Plan** | LLM produces a step plan held in structured agent state | `agent/` |
| **Execute** | Each step calls a tool (Playwright browser actions, ERP APIs) | `tools/` |
| **Policy gate** | Every tool call is checked against permissions; risky actions pause for human approval | `policy/` |
| **Observe** | Tool results and page state are recorded back into agent state | `agent/` |
| **Adapt** | On failure, recover (retry, alternate approach, replan) or escalate | `recovery/` |
| **Verify** | A separate check confirms the goal was achieved, independent of the agent's own claim | `verification/` |
| **Complete** | Final result, audit log, and evidence written to `runs/<run_id>/` | `database/`, `runs/` |

Supporting pieces:

- **Audit logging and evidence:** every decision, tool call, and approval is recorded; screenshots and artifacts are saved per run.
- **Background execution:** runs execute in ARQ workers backed by Redis, triggered through the FastAPI API.
- **Frontend:** a small UI for submitting goals, watching runs, and approving actions (later phase).

## MiniERP

MiniERP is a small mock ERP (Flask + SQLite) that exists purely as a **test environment** for the agent. It holds no real data and never talks to any real ERP. It supports both browser interaction (for Playwright) and a JSON API.

### Start it

From the repository root, with the virtualenv active:

```bash
python -m erp
```

It listens on <http://127.0.0.1:8001> (override with `MINIERP_PORT`). The database is created and seeded on first start at `data/minierp.db`. To reset to a clean seeded state, stop the server and delete that file.

**Test credentials:** `admin` / `admin123`

### Pages

| URL | What it does |
|---|---|
| `/login`, `/logout` | Session login and logout |
| `/dashboard` | Totals and the 5 most recent bills |
| `/bills` | All bills, newest first |
| `/bills/new` | Form: `vendor`, `invoice_number`, `amount`, `invoice_date` (YYYY-MM-DD), `description` |

Form fields and buttons have stable `id` attributes (`#vendor`, `#invoice_number`, `#amount`, `#invoice_date`, `#description`, `#submit-bill`, `#login-button`, ...). Creating a bill redirects to `/bills` with a success message. Validation errors re-render the form with HTTP 400; a duplicate (same vendor + invoice number) returns 409. An unknown vendor name is created automatically.

### JSON API

The API uses the same session cookie as the browser, so log in first (`POST /login` with form fields `username` and `password`). Without a session it returns `401`.

| Endpoint | Result |
|---|---|
| `GET /api/bills` | `{"bills": [...]}`, newest first |
| `GET /api/bills/<id>` | One bill, or `404` |
| `POST /api/bills` | JSON body with the five fields. `201` + the bill, `400` on validation errors, `409` on duplicates |

### Deliberate failure mode: session expiry

Set `MINIERP_SESSION_EXPIRY_ACTIONS=N` (default `0` = off). Every successful authenticated **browser** request (a page view, or a form submission that succeeds) counts as one action. After N actions, the *next* browser request is **not executed**: the session is cleared and the browser is redirected to `/login?expired=1`, where a "session has expired" message is shown. If that request was a form submission, **the submission is lost**. Logging in again resets the counter.

Details: failed submissions (HTTP 4xx) don't count, and API calls neither count nor trigger expiry (they just return `401` once the session is gone). It is fully deterministic, so the agent's recovery (notice, re-login, retry, verify) can be tested reliably.

```bash
MINIERP_SESSION_EXPIRY_ACTIONS=2 python -m erp
```

With N=2: dashboard (action 1), open `/bills/new` (action 2), submit the form: bounced to login, bill not created.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MINIERP_PORT` | `8001` | Port |
| `MINIERP_DB_PATH` | `data/minierp.db` | SQLite file |
| `MINIERP_SECRET_KEY` | dev value | Session signing key |
| `MINIERP_SESSION_EXPIRY_ACTIONS` | `0` | Session-expiry failure mode (above) |

These are plain environment variables; `.env` is not loaded automatically.

### Sample invoice

`data/invoice_acme.txt` is the source document the agent will read: vendor, invoice number, amount, invoice date, and description. The matching vendor exists in the seed data, but this invoice number does not, so entering it is a clean create.

## Requirements

- Python 3.12

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # not read by any code yet
```

## Run the FastAPI server

From the repository root:

```bash
uvicorn backend.app.main:app --reload
```

Then open <http://127.0.0.1:8000/health>. You should see `{"status":"ok"}`. Interactive docs are at <http://127.0.0.1:8000/docs>.

## Run the tests

From the repository root:

```bash
pytest
```

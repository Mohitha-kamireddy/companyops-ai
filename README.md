# CompanyOps AI

An autonomous enterprise AI operator that runs a mock company ERP through browser automation and APIs.

Built as an engineering hiring assignment. The point is to show a **controlled, observable agent loop** that we write and understand ourselves, with no agent frameworks (no LangChain, LangGraph, CrewAI, AutoGen, etc.).

```
Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Complete
```

## Status

**Phase 1: project skeleton only.** There is no agent, no LLM integration, no ERP, and no frontend yet. The only running code is a FastAPI app with a `/health` endpoint.

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
erp/               Mock company ERP
data/              Seed data and local databases (contents git-ignored)
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

## Requirements

- Python 3.12

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # not read by any code yet
```

## Run the server

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

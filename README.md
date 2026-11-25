# Workflow Observatory

Prose word count: 544 (excluding code and setup commands).

A local browser application for supervising multi-agent research: inspect a proposed plan, follow its execution, edit the workflow, and export a source-linked report.

## Status and capabilities

- Implemented: plan preview; live step status, inputs, outputs and tool records; source inspection; text, form and graph edits with preview and application.
- Implemented: one automatic evidence-repair round; intermediate-result revision and downstream reruns; step-boundary pause/resume, failure retry, saved tasks, Markdown and run-JSON exports.
- The interface is English. Tasks execute sequentially. Graph dragging changes layout only; node positions are not persisted. Result revision uses JSON.
- Full historical playback, file import, custom roles, parallel execution, accounts and hosted deployment are not implemented. No participant study has been conducted.

## Technology

| Component | Technology and role |
|---|---|
| Interface | React, TypeScript, React Flow and Tailwind: graph editing, inspection and reports. |
| Backend | FastAPI and Pydantic: API and plan validation; Python scheduler: dependency-ready execution. |
| Execution and storage | LangGraph: individual step execution and checkpoints; SQLite: tasks, versions, results and events. |
| Models and tools | Separate Planner, Researcher, Reviewer and Writer calls share the configured DeepSeek model. DeepSeek Search/Fetch is the default web provider; Tavily is optional. |

## Run locally

Requires Python 3.11, Node.js 22.12+ compatible with Vite 7, npm, network access and your own funded DeepSeek API key. Commands use a POSIX shell.

```sh
git clone https://github.com/Llanuras/iis-workflow-observatory.git
cd iis-workflow-observatory
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
cp .env.example .env
```

Set your key in the local `.env` file:

```dotenv
DEEPSEEK_API_KEY=your_key
DEEPSEEK_MODEL=deepseek-flash
SEARCH_PROVIDER=deepseek
MAX_SEARCHES=3
MAX_PAGES=5
```

Never commit `.env` or API keys. The default model and web tools use the same key. Live calls consume provider credit; the search/page limits are not a monetary spending cap.

```sh
cd frontend
npm ci
npm run build
cd ..
./run.sh
```

Open [localhost:8000](http://127.0.0.1:8000/). Keep the terminal running; stop with `Ctrl+C`. Later starts need only `./run.sh`. Rebuild after frontend changes and restart after configuration changes. A fresh clone contains no saved tasks.

## Inspect and control a task

1. Enter a research question and select **Create plan**. Review the steps and dependencies, then select **Start workflow**.
2. Select a graph node to inspect its objective, inputs, output, sources and call records.
3. Change the plan using text, **Edit step**, or **Edit workflow**. Review the preview and rerun scope before **Apply changes**. For active work, request **Pause** and wait for **Paused** first.
4. To correct completed work, preview a redo or revise its JSON output. Applying preserves history and invalidates affected downstream results; resume to regenerate them.
5. Open **View report** and export **Markdown**, **Run data**, or **Print / PDF**. Reopen saved work from **Tasks**.

Automatic evidence repair can add research and review steps. If the single repair round is insufficient, the task enters **Needs help**. Inspect the issue, edit or correct the work, then resume. A pause waits for the current operation; restarting interrupted work may repeat an external call. Provider switching requires configuration by the operator.

Source links and review records support inspection; they do not guarantee factual correctness. Task data is stored locally, while instructions and relevant evidence are sent to configured services. The server binds to loopback and is intended for local use.

## Checks and project files

Run offline checks from the project root:

```sh
.venv/bin/pytest -q
```

The recorded run passed 14 tests with injected services. Three live development cases are recorded separately; neither constitutes a participant study.

- [Development record](docs/DEVELOPMENT.md): significant changes, reasons and checks.
- [Acceptance evidence](docs/evidence/acceptance.json): recorded live cases.
- [Project report](docs/submission/A2_Project_Report.pdf) and [interaction figures](docs/figures/).
- Source: `frontend/src/` for the interface; `backend/app/` for the API, scheduling, validation, services and storage; `backend/tests/` for tests.

# ProjectSystem — React + Python + MySQL

The project planner, rebuilt as three parts:

```
backend/    Python API (FastAPI + SQLAlchemy)  ->  talks to MySQL          runs on http://localhost:8000
frontend/   React UI (Vite)                     ->  talks to the API        runs on http://localhost:5173
backend/schema.sql   the MySQL tables (same schema as the C# version)
```

The scheduling engine, the lock rules and the audit trail live in the Python
backend. The React app only displays and edits.

---

## 1. Install these once

| What | Where | Note |
|---|---|---|
| Python 3.11 or newer | https://www.python.org/downloads/ | On the first installer screen tick **"Add python.exe to PATH"** |
| Node.js LTS | https://nodejs.org/ | Installs `npm` too |
| MySQL 8 | already installed | Remember the root password |

Check they work — open **Command Prompt** and type:

```
python --version
node --version
npm --version
```

Each should print a version number.

## 2. Create the database (once)

Open **MySQL Workbench**, connect to your local server, then
File → Open SQL Script → choose `backend/schema.sql` → click the lightning-bolt ⚡ (Execute).

This creates a database called `projectsystem` with all tables.

## 3. Start the backend (Python)

Open a Command Prompt **inside the `backend` folder** (in File Explorer, click the
address bar, type `cmd`, press Enter). Then:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Now open `backend\.env` in Notepad and put your MySQL password in:

```
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/projectsystem
```

Optional but recommended — load sample data so the screens are not empty:

```
python seed.py
```

Start the API:

```
uvicorn app.main:app --reload --port 8000
```

Leave this window open. You can browse the API at **http://localhost:8000/docs**
(every endpoint, with a "Try it out" button).

> Next time you only need: `.venv\Scripts\activate` then `uvicorn app.main:app --reload --port 8000`

## 4. Start the front end (React)

Open a **second** Command Prompt inside the `frontend` folder:

```
npm install
npm run dev
```

Open **http://localhost:5173** in your browser. Done.

> Next time you only need `npm run dev`.

## 5. Using the app

Type your name in the **"Acting as"** box at the top right. It is written into
the audit trail with every change (it is a record, not a login).

| Page | What you do there |
|---|---|
| **Portfolio** | Create / edit / delete projects. Planned end vs the forecast the engine computes. "Open plan" jumps to the plan. |
| **Plan** | The outline grid + Gantt. Select a row, then use the toolbar: **+ Milestone**, **+ Task**, **+ Subtask**, **Edit…**, **Delete**, **↑ ↓** (reorder), **← →** (outdent / indent), **Baseline**. Double-click a row to edit it. |
| **Milestones** | Every milestone across all projects: target vs forecast vs actual. |
| **Assignments** | Workload per person; shared activities split their days. |
| **Team** | Organisations, roles, people — create, edit, delete. |
| **Audit** | The append-only trail, filterable by project, kind and text. |

Rules the backend enforces (you'll see a red notice explaining any refusal):

- A task must sit under a milestone; a subtask under a task.
- **The plan locks when work starts.** Once an activity (or anything beneath it)
  has an actual start/finish, its planned dates, duration, mode and links can't
  change. Actuals, progress, notes, role and assignees always can.
- The first actual date **pins** an Auto activity to where it currently sits.
- Nothing with recorded work can be deleted or moved — that includes whole projects.
- Dependency loops are refused. An activity that still drives others can't be deleted until those links are removed.

## 6. Run the tests

```
cd backend
.venv\Scripts\activate
pytest -q
```

Two tests: the engine must reproduce `tests/golden.json` exactly, and a full
API run (create → edit → lock → refuse → move → delete) on a throwaway SQLite
database, so it needs no MySQL.

## 7. Common errors

| Message | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python and tick "Add to PATH", or use `py` instead of `python`. |
| `Access denied for user 'root'@'localhost'` | Wrong password in `backend\.env`. |
| `Unknown database 'projectsystem'` | Step 2 not done — run `schema.sql`. |
| `Can't connect to MySQL server on 'localhost'` | MySQL service is not running (Services → MySQL80 → Start). |
| `[Errno 10048] ... port 8000` / `Port 5173 is in use` | Something else is using the port. Close it, or run with `--port 8001` and change `vite.config.js` proxy target to match. |
| Browser shows "Failed to fetch" | The backend window is not running, or it's on a different port than `vite.config.js` expects. |
| `pip install` fails on `cryptography` | Run `python -m pip install --upgrade pip` and retry. |

## 8. Where things are

```
backend/app/scheduling/engine.py       forward pass, rollup, CPM backward pass (golden-tested)
backend/app/scheduling/work_calendar.py working-day index <-> date (weekends + holidays)
backend/app/services/plan.py           add / update / delete / move / baseline, lock rules applied here
backend/app/services/rules.py          lock rules, RuleViolation -> HTTP 409
backend/app/services/audit.py          append-only trail writer
backend/app/routers/*.py               the REST endpoints
backend/app/models.py                  ORM = schema.sql
frontend/src/api.js                    every API call the UI makes
frontend/src/pages/*.jsx               one file per page
frontend/src/components/Gantt.jsx      the chart (divs + SVG arrows, no library)
frontend/src/components/ActivityEditor.jsx  the activity dialog
```

## 9. Running for real (not on your PC)

`npm run build` produces `frontend/dist` — static files any web server can
host. Run the backend with `uvicorn app.main:app --host 0.0.0.0 --port 8000`
and set `CORS_ORIGINS` in `.env` to the address the UI is served from.
Authentication is not included; put a login in front before exposing it.

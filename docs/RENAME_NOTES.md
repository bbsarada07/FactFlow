# Rename notes: NemesisAI to FactFlow

This file records what the rename changed for a running setup and what you need to do by hand. None of the
commands below were run by the rename itself.

## Database

| Setting | Before | After |
|---|---|---|
| PostgreSQL database name (`backend/.env.example`) | `nemesisai` | `factflow` |
| SQLite fallback file (`backend/config.py`, `backend/database/connection.py`) | `backend/nemesisai.db` | `backend/factflow.db` |

There are no migrations. On first start the backend creates its tables and loads the seed data (incidents and
known patterns), so a new, empty database is all that is needed.

**If you use PostgreSQL** (PowerShell, with `psql`/`createdb` on PATH):

```powershell
createdb -U postgres factflow
# or: psql -U postgres -c "CREATE DATABASE factflow;"
```

Then make sure your local `backend/.env` points at it:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/factflow
ASYNC_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/factflow
```

Start the backend (`uvicorn main:app --reload --port 8000`); tables and seed data are created automatically.
An existing `nemesisai` database is left untouched. Only if you want to carry its rows over (for example past
registry verdicts) into the new database, copy them before the first start:

```powershell
pg_dump -U postgres nemesisai | psql -U postgres factflow
```

**If you use the SQLite fallback:** nothing to do. A fresh `backend/factflow.db` is created and seeded on first
start. An old `backend/nemesisai.db`, if present, is no longer read; delete it yourself once you no longer need it.

## Redis and Celery

| Setting | Before | After |
|---|---|---|
| Redis event-stream key prefix (`services/event_bus.py`) | `nemesis:events:` | `factflow:events:` |
| Celery app name (`tasks/pipeline_task.py`) | `nemesisai` | `factflow` |
| Celery task name | `nemesisai.run_pipeline` | `factflow.run_pipeline` |

Only relevant with `USE_CELERY=true`. Stop the API and the Celery worker, then start both again together.
Tasks still queued under the old task name are rejected by the new worker, and any live progress stream that was
mid-run during the switch is lost. Redis holds no verdict cache: verdicts are reused from the public registry in
the database, so a new, empty `factflow` database also starts with an empty registry (unless you copy the old rows
as described above).

## Frontend

The package name changed from `nemesisai-frontend` to `factflow-frontend` (`package.json` and
`package-lock.json`). Downloaded Myth-vs-Fact cards are now named `factflow-<verdict>-<id>.png`.

## Browser extension

Renamed identifiers, all changed together in one commit:

| Kind | Before | After |
|---|---|---|
| Runtime message types | `NEMESIS_PENDING`, `NEMESIS_RESULT`, `NEMESIS_ERROR`, `NEMESIS_GET_SELECTION`, `NEMESIS_GET_CONTEXT_TARGET`, `NEMESIS_VERIFY_TEXT`, `NEMESIS_VERIFY_ACTIVE_SELECTION` | `FACTFLOW_*` |
| Context-menu IDs | `nemesis-verify`, `nemesis-verify-message` | `factflow-verify`, `factflow-verify-message` |
| Custom elements | `<nemesis-badge>`, `<nemesis-inline>`, `<nemesis-hover>` | `<factflow-badge>`, `<factflow-inline>`, `<factflow-hover>` |
| Load guard | `window.__nemesisLoaded` | `window.__factflowLoaded` |
| Icons | red "N" monogram | red "F" monogram |

Storage keys (`apiBase` in `chrome.storage.sync`, `history` in `chrome.storage.local`) were not renamed, so the
saved backend URL and recent checks survive.

To reload it in Edge (`edge://extensions`) or Chrome (`chrome://extensions`): click **Reload** on the extension
card, then refresh any open WhatsApp Web, X or Instagram tabs so the new content script is injected. Tabs that
were open before the reload still run the old script and cannot talk to the new service worker until refreshed.

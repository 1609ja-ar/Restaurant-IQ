# RestaurantIQ — How to Run (Windows PowerShell)

> **Prerequisites**: Python 3.11, Node.js 18+, MongoDB 6.0+ (local Community Server, or a free MongoDB Atlas cluster)

---

## ⚠️ Common Error & Root Cause

If you see:
```
ModuleNotFoundError: No module named 'app'
```

**This means you ran `uvicorn` from the wrong directory.**  
The `app/` folder lives inside `restaurantiq/backend/`, so you **must `cd` there first** before starting the server.

---

## Quick Start (scripts — work from ANY folder)

These scripts find the right folders and the project's own Python (`backend\.venv`) by themselves,
so you never get "Could not open requirements file" or "No module named 'app'".

```powershell
# once: install everything
powershell -ExecutionPolicy Bypass -File "C:\Users\jaide\Desktop\Data prj\restaurantiq\setup.ps1"
# once: check MongoDB (must print "OK: connected to MongoDB ..."; see Step 1b to install it)
& "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend\.venv\Scripts\python.exe" -m app.db_check

# every time - window 1
powershell -ExecutionPolicy Bypass -File "C:\Users\jaide\Desktop\Data prj\restaurantiq\start-backend.ps1"
# every time - window 2
powershell -ExecutionPolicy Bypass -File "C:\Users\jaide\Desktop\Data prj\restaurantiq\start-frontend.ps1"
```

In VS Code you can instead use **Terminal → Run Task… → "RestaurantIQ: …"**.

Do not use plain `python` / `pip`: on this PC they are Anaconda's, not the project's environment.

---

## First-Time Setup

Do this **once** to install all dependencies.

### Step 1 — Backend (Python virtual environment)

Open **PowerShell Terminal 1** and run:

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell blocks `Activate.ps1` with an execution policy error, run instead:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> Then retry `.\.venv\Scripts\Activate.ps1`.

### Step 1b — Database (MongoDB, once)

RestaurantIQ stores accounts, dataset versions, cleaned rows, quality reports and settings in **MongoDB**.
There is no database user or table to create by hand: the backend creates its collections and indexes itself
on startup.

**Option A — MongoDB on this PC (recommended)**

1. Download **MongoDB Community Server** (Windows x64, MSI, version 8.0) from
   https://www.mongodb.com/try/download/community
2. Run the installer: choose **Complete** and keep **Install MongoD as a Service** ticked (service name
   `MongoDB`). MongoDB Compass is optional (a viewer for the data).
3. Check that it runs, then check the connection:

```powershell
Get-Service MongoDB          # Status must be Running (if not, as administrator: net start MongoDB)
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\python.exe -m app.db_check
```

`backend\.env` already contains the right settings for a local server:
`RIQ_MONGO_URI=mongodb://127.0.0.1:27017` and `RIQ_MONGO_DB=restaurantiq`.

**Option B — MongoDB Atlas (cloud, free tier)**

Create a free cluster at https://cloud.mongodb.com, add a database user (Database Access) and your IP address
(Network Access), then **Connect → Drivers** and paste the `mongodb+srv://...` string into `RIQ_MONGO_URI` in
`backend\.env`. Special characters in the password must be URL-encoded (`@` → `%40`, `:` → `%3A`,
`/` → `%2F`, `#` → `%23`). Run `python -m app.db_check` to confirm.

**Optional:** if you used the app earlier in local-file mode, copy that data (accounts, dataset versions,
settings) from `backend\data` into MongoDB once: `.\.venv\Scripts\python.exe -m app.db_import`.
Details: `docs\database\README.md`.

### Step 1c — Groq API key (optional)

1. Create a free key at https://console.groq.com/keys (it starts with `gsk_`).
2. Open `backend\.env` and replace `your_groq_key_here` in `GROQ_API_KEY=your_groq_key_here` with your key.
   Keep `LLM_PROVIDER=groq`.
3. Restart the backend and open http://127.0.0.1:8010/api/test-llm — it should return
   `"reply": "RestaurantIQ connection OK"`.

Without a key the AI Analyst runs in labeled Demo Mode. The key is read only by the backend; it is never sent to
the browser or written to logs. If Groq retires the default model, pick one from
https://console.groq.com/docs/models and set `GROQ_MODEL=` in `backend\.env`.
(To use Claude instead, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.)

### Step 2 — Frontend (Node.js packages)

Open **PowerShell Terminal 2** and run:

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm install
```

---

## Running the App (Every Time)

You need **two terminals** open at the same time.

### Terminal 1 — Start the Backend (FastAPI on port 8010)

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

> **If activation fails**, skip it and call the venv Python directly:
> ```powershell
> cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
> .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
> ```

✅ You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8010
```

Verify with: http://127.0.0.1:8010/api/health  → should return `"status":"ok"` and `"database": {"connected": true, ...}`  
If `connected` is `false`, the `error` field says what to fix (usually: start the MongoDB service).  
Check the AI key with: http://127.0.0.1:8010/api/test-llm (a short reply, or a clear error)  
API docs: http://127.0.0.1:8010/docs

### Terminal 2 — Start the Frontend (Vite dev server on port 5173)

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm run dev
```

✅ You should see Vite print something like:
```
  VITE v5.4.11  ready in 500 ms
  ➜  Local:   http://localhost:5173/
```

### Open the App

Go to **http://localhost:5173** in your browser.

You will see the **Sign in** page. The first time, click **Create one** and register (name, email,
password with at least 8 characters including a letter and a number). The first account you create also
gets the datasets you imported before login existed.

Then click **Data → Load Demo Dataset** to load sample data, or upload your own CSV/XLSX.
Sign out from the account menu (top right). Sessions last 60 minutes.

---

## Key URLs

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | Main app (React frontend) |
| http://127.0.0.1:8010/api/health | Backend + database health check |
| http://127.0.0.1:8010/api/test-llm | Verifies the Groq (or Anthropic) API key with a short reply |
| http://127.0.0.1:8010/docs | FastAPI interactive API docs (Swagger UI) |

---

## Stopping the Servers

- Press **Ctrl+C** in each terminal to stop the server running there.

---

## Environment Variables (Optional)

Copy `.env.example` to `restaurantiq/backend/.env` and fill in as needed:

```powershell
Copy-Item "C:\Users\jaide\Desktop\Data prj\restaurantiq\.env.example" `
          "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend\.env"
```

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_PROVIDER` | AI provider for the AI Analyst: `groq` or `anthropic` | `groq` |
| `GROQ_API_KEY` | Groq key (`gsk_...`). Without it the analyst runs in **Demo Mode**. | placeholder |
| `GROQ_MODEL` | Groq model used for explanations | `openai/gpt-oss-120b` |
| `ANTHROPIC_API_KEY` | Only used when `LLM_PROVIDER=anthropic` | placeholder |
| `RIQ_LLM_MODEL` | Claude model to use for AI explanations | `claude-opus-5-5` |
| `RIQ_STORAGE` | `mongodb` (database of record) or `file` (local files; used by the tests) | `mongodb` |
| `RIQ_MONGO_URI` | MongoDB connection string (local or Atlas `mongodb+srv://`) | `mongodb://127.0.0.1:27017` |
| `RIQ_MONGO_DB` | Database name | `restaurantiq` |
| `RIQ_MONGO_TIMEOUT_MS` | How long to wait before MongoDB is reported unreachable | `5000` |
| `RIQ_DATA_DIR` | Folder for raw uploaded files (checksums live in MongoDB) | `backend/data` |

---

## Running Tests

### Backend Tests (431 tests)

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```

Expected: `419 passed, 12 skipped`. The 12 MongoDB tests run when you point them at a MongoDB server:
`$env:RIQ_TEST_MONGO_URI = "mongodb://127.0.0.1:27017"` (each test creates and drops its own `riq_test_*`
database; your `restaurantiq` database is not touched). Then the result is `431 passed`.

### Frontend Tests (9 tests, all should pass)

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm test
```

Expected: `9 passed`

### Frontend TypeScript Check + Production Build

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm run build
```

Expected: `✓ built in X.XXs` with no TypeScript errors.

---

## Troubleshooting

### `Could not open requirements file: ... 'requirements.txt'`

**Cause**: `pip` was run from a folder that has no `requirements.txt` (for example `Data prj`).

**Fix**: run it from the `restaurantiq\backend` folder (the only place `requirements.txt` lives), or run the setup script, which works from anywhere:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\jaide\Desktop\Data prj\restaurantiq\setup.ps1"
```

### Login or sign-up page says "Cannot reach MongoDB ..." (or another MongoDB message)

**Cause**: the backend could not use the database in `RIQ_MONGO_URI` (`backend\.env`). The message names the
reason; `db_check` shows it too:

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
Get-Service MongoDB                              # local server: Status must be Running
.\.venv\Scripts\python.exe -m app.db_check     # must print "OK: connected to MongoDB ..."
```

| `db_check` says | Meaning | Fix |
|---|---|---|
| `FAIL (not running)` | nothing answers at the host:port in `RIQ_MONGO_URI` | start the service: `services.msc` → MongoDB Server → Start (or `net start MongoDB` as administrator); check the port |
| `FAIL (unknown host)` | the host name cannot be found | fix the address; for Atlas paste the full `mongodb+srv://` string |
| `FAIL (auth failed)` | wrong user name or password in the URI | correct them; URL-encode special characters (`@` → `%40`, `:` → `%3A`) |
| `FAIL (auth required)` | the server needs a login but the URI has none | use `mongodb://user:password@host:port/?authSource=admin` |
| `FAIL (no privileges)` | the user may not use database `restaurantiq` | give it the `readWrite` role on that database |
| `FAIL (bad uri)` | the connection string is malformed (often an unencoded `@` or `:` in the password) | fix `RIQ_MONGO_URI` |
| `FAIL (tls)` | secure connection failed (Atlas) | add your IP under Network Access |

The backend keeps running while MongoDB is down and recovers by itself once MongoDB is back; no restart is
needed. `db_check` prints the URI with the password replaced by `****`; the password is never printed or logged.

### `ModuleNotFoundError: No module named 'app'`

**Cause**: You are running `uvicorn` from the wrong directory.

**Fix**: Always `cd` into `restaurantiq\backend` **before** running uvicorn:
```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### `[Errno 10048]` or `[WinError 10013]` — port 8010 already in use / access denied

**Cause**: A previous backend process is still holding port 8010. This often happens after closing a terminal without pressing Ctrl+C, or if you have two terminal sessions.

**Fix**: Kill the old process and restart:
```powershell
# Step 1: find the PID of whatever owns port 8010
Get-NetTCPConnection -LocalPort 8010 | Select-Object OwningProcess

# Step 2: kill it (replace 12345 with the PID shown above)
Stop-Process -Id 12345 -Force

# Step 3: start the backend again
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

### PowerShell blocks `Activate.ps1` (execution policy error)

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then retry `.\.venv\Scripts\Activate.ps1`.

### Frontend shows "API not reachable" or blank data

- Make sure the **backend is running** on port 8010 first (check http://127.0.0.1:8010/api/health).
- The Vite dev server proxies `/api` requests to `http://127.0.0.1:8010` automatically.

### `npm install` fails or `node_modules` is missing

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm install
npm run dev
```

---

## Project Structure (Quick Reference)

```
restaurantiq/
├── backend/              ← FastAPI + pandas + DuckDB (Python 3.11)
│   ├── .venv/            ← Python virtual environment (created by you)
│   ├── app/
│   │   ├── main.py       ← API routes (entry point for uvicorn)
│   │   ├── ingest.py     ← CSV/XLSX upload & schema discovery
│   │   ├── cleaning.py   ← 9 data-cleaning rules
│   │   ├── kpis.py       ← KPI calculations and filters
│   │   ├── db.py         ← MongoDB storage (collections, indexes, error messages)
│   │   ├── db_check.py   ← python -m app.db_check: connection test
│   │   ├── analyst.py    ← AI analyst (Claude integration)
│   │   └── ...           ← other modules
│   ├── tests/            ← pytest test suite (431 tests)
│   └── requirements.txt  ← Python dependencies
├── frontend/             ← React 18 + Vite + TypeScript + Tailwind
│   ├── node_modules/     ← JS dependencies (created by npm install)
│   ├── src/
│   │   ├── pages/        ← Dashboard, Explorer, Market, Compare, etc.
│   │   └── components/   ← Shared UI components
│   └── vite.config.ts    ← Dev server config (proxies /api → :8010)
├── .env.example          ← Template for environment variables
├── HOW_TO_RUN.md         ← This file
└── README.md             ← Full project documentation
```


# RestaurantIQ — How to Run (Windows PowerShell)

> **Prerequisites**: Python 3.11, Node.js 18+

---

## ⚠️ Common Error & Root Cause

If you see:
```
ModuleNotFoundError: No module named 'app'
```

**This means you ran `uvicorn` from the wrong directory.**  
The `app/` folder lives inside `restaurantiq/backend/`, so you **must `cd` there first** before starting the server.

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

Verify with: http://127.0.0.1:8010/api/health  → should return `{"status":"ok"}`  
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

Then click **Data → Load Demo Dataset** to load sample data, or upload your own CSV/XLSX.

---

## Key URLs

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | Main app (React frontend) |
| http://127.0.0.1:8010/api/health | Backend health check |
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
| `ANTHROPIC_API_KEY` | Enables live AI explanations in the AI Analyst. Without it the analyst runs in **Demo Mode**. | unset |
| `RIQ_LLM_MODEL` | Claude model to use for AI explanations | `claude-opus-5-5` |
| `RIQ_DATA_DIR` | Where uploads, dataset versions, and settings are stored | `backend/data` |

---

## Running Tests

### Backend Tests (328 tests, all should pass)

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```

Expected: `328 passed`

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
│   │   ├── analyst.py    ← AI analyst (Claude integration)
│   │   └── ...           ← other modules
│   ├── tests/            ← pytest test suite (328 tests)
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


# RestaurantIQ

**Turn Restaurant Data Into Smarter Business Decisions.**

RestaurantIQ is a portfolio analytics product that imports any reasonably structured restaurant dataset (CSV or
XLSX), cleans it with documented and tested rules, and turns it into KPIs, market analysis, statistical tests,
comparisons, an AI-assisted analyst, PDF reports and BI exports. Every number is computed by the backend from the
active dataset version, and every KPI or chart can show its real pandas code and the DuckDB SQL that reproduces it.

## Architecture

```
restaurantiq/
  backend/                 FastAPI + pandas + DuckDB + MongoDB (Python 3.11)
    app/
      main.py              API routes, friendly JSON errors, no app-level upload size limit
      ingest.py            file-type sniffing, chunked CSV / streaming XLSX reading, schema discovery + mapping suggestions
      cleaning.py          the 9 cleaning rules, reconciliation, data-quality report (deterministic)
      kpis.py              filters, analysis context, Bayesian prior, descriptive KPIs and chart data
      stats.py             market analysis, Opportunity Score, Spearman, Mann-Whitney
      calculations.py      registry: pandas function + DuckDB SQL + PASS/FAIL comparison ("Show calculation")
      sql_queries.py       DuckDB tables, filter -> SQL, metric SQL, read-only SQL Playground
      compare.py           2-4 way comparisons using the same KPI functions
      analyst.py           question -> intent -> deterministic analysis -> JSON -> optional Claude explanation
      reports.py           report builder + reportlab PDF renderer
      exports.py           filtered CSV, BI flat CSV, star-schema ZIP
      demo_data.py         deterministic synthetic sample (seed 42)
      auth.py              accounts, bcrypt, JWT cookie sessions, login rate limiting, route protection
      config.py            settings from environment / backend/.env (python-dotenv); secrets never logged
      db.py                MongoDB store: collections + indexes (accounts, versions, cleaned rows, log, quality,
                           settings), friendly connection errors
      db_check.py          python -m app.db_check: connection test that prints OK or the exact failure
      db_import.py         python -m app.db_import: optional one-time copy of local-file data into MongoDB
      store.py             local-file store with the same interface (tests, RIQ_STORAGE=file)
      services/claude_client.py   single Anthropic client: ask_claude(prompt, system=None)
    tests/                 pytest suite (cleaning rules, KPI hand calculations, pandas-vs-DuckDB, API, scale)
  frontend/                React 18 + Vite + TypeScript + Tailwind 3 + Recharts + React Query
    src/pages/             Dashboard, Explorer, Market Analysis, Compare, SQL Playground, AI Analyst,
                           Reports, Data, Methodology, Settings
    src/components/        app shell, filter bar, KPI cards, charts, Show calculation dialog, UI primitives
    src/lib/               API client, formatting, theme logic (+ vitest unit tests)
  notebooks/validation.ipynb   independent re-implementation of cleaning/KPIs vs the API (PASS/FAIL)
  docs/                    kpi_definitions.md, data_dictionary.md, assumptions_log.md, database/ (MongoDB collections and indexes)
```

Data flow: **upload → profile & suggested mapping → user-confirmed mapping → quality check → import (new version)
→ analysis context (cached per version + settings) → filtered analytics / SQL / reports / exports**.

## Setup and run (Windows PowerShell)

Prerequisites: Python 3.11, Node.js 18+, MongoDB 6.0+ running locally (Community Server, Windows service
`MongoDB`) or a MongoDB Atlas connection string in `RIQ_MONGO_URI`.

**Terminal 1 - backend** (port 8010; port 8000 may be blocked on some Windows PCs):

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.db_check                 # must print "OK: connected to MongoDB ..."
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

- Health: <http://127.0.0.1:8010/api/health> returns `"status":"ok"` plus the database connection status
- Anthropic key check: <http://127.0.0.1:8010/api/test-claude>
- API docs: <http://127.0.0.1:8010/docs>

**Terminal 2 - frontend:**

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\frontend"
npm install
npm run dev
```

Open the URL Vite prints (usually <http://localhost:5173>). The Vite dev proxy forwards `/api` to
`http://127.0.0.1:8010`. Then go to **Data → Load Demo Dataset**, or upload your own file.

If PowerShell blocks `Activate.ps1`, skip activation and call `.\.venv\Scripts\python.exe` directly.

### Tests and checks

```powershell
# backend (from backend/)
python -m pytest -q
# frontend (from frontend/)
npm run build      # TypeScript check + production build
npm test           # vitest unit tests (theme, formatting, filter serialization)
```

The validation notebook needs the backend running: open `notebooks/validation.ipynb` in Jupyter (or VS Code) and
run all cells. Regenerate it from `notebooks/build_validation_notebook.py` if you edit it.

## Environment variables

Copy `.env.example` to `backend/.env` (never commit real keys).

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables live AI explanations in AI Analyst. Without it the analyst runs in labeled **Demo Mode**. | placeholder |
| `RIQ_LLM_MODEL` | Claude model used to explain computed results | `claude-opus-5-5` |
| `RIQ_STORAGE` | `mongodb` (database of record) or `file` (tests) | `mongodb` |
| `RIQ_MONGO_URI` | MongoDB connection string (local, or Atlas `mongodb+srv://`; URL-encode special characters in the password) | `mongodb://127.0.0.1:27017` |
| `RIQ_MONGO_DB` | Database name | `restaurantiq` |
| `RIQ_MONGO_TIMEOUT_MS` | Wait before MongoDB is reported unreachable | `5000` |
| `RIQ_DATA_DIR` | Folder for raw uploaded files (their SHA-256 checksums are stored in MongoDB) | `backend/data` |

The Anthropic key is read only by the backend (`app/config.py` → `app/services/claude_client.py`). The React app
calls the backend, never Anthropic, so the key is never exposed to the browser; it is also never logged.

## Authentication

Every page and every API route requires signing in, except `GET /api/health`, the sign-in/sign-up endpoints
and the API docs (`/docs`). Each account sees **only its own datasets**, uploads and reports.

### Set up

1. `backend\.env` already contains a generated `JWT_SECRET`. To make a new one:
   ```powershell
   cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   Paste the output after `JWT_SECRET=` (keep it private; changing it signs everyone out).
2. Start the backend and frontend (see *Setup and run*), open <http://localhost:5173>, choose **Create one**
   and register. **The first account you create also receives the datasets imported before login existed**
   (unless a demo account is configured — then the demo account receives them).

### Auth settings (`backend\.env`)

| Variable | Purpose | Default |
|---|---|---|
| `JWT_SECRET` | Signs session tokens. Required (32+ chars) when `RIQ_ENV=production`; in development a temporary secret is used if missing (everyone is signed out on restart). | generated |
| `JWT_EXPIRE_MINUTES` | Session length | `60` |
| `ALLOW_REGISTRATION` | `false` hides **Create account** and rejects new sign-ups | `true` |
| `DEMO_USER_EMAIL` / `DEMO_USER_PASSWORD` | Optional **demo account**, created on first startup; enables the *Use demo account* button. Use a normal address such as `demo@example.com` (reserved domains like `.local` are rejected). | empty |
| `RIQ_ENV` | `production` makes a missing/short `JWT_SECRET` a startup error | `development` |
| `COOKIE_SECURE` | `true` when served over HTTPS (cookie only sent over HTTPS) | `false` |
| `CORS_ORIGINS` | Comma-separated frontend origins allowed to call the API | `http://localhost:5173,http://127.0.0.1:5173` |

> **Demo account:** if you set `DEMO_USER_EMAIL`, that account is a shared demo login (anyone with the app can
> use *Use demo account*). Do not put real data in it and do not enable it on a server other people can reach.

### Endpoints

| Method | Path | Access |
|---|---|---|
| GET | `/api/auth/config` | public — `allow_registration`, `demo_available` |
| POST | `/api/auth/register` | public (if enabled) — name, email, password |
| POST | `/api/auth/login` | public — email, password |
| POST | `/api/auth/demo-login` | public — only when a demo account is configured |
| POST | `/api/auth/logout` | public — ends the session |
| GET | `/api/auth/me` | signed in |
| POST | `/api/auth/change-password` | signed in — signs out all other sessions |

### Security notes and limitations

- Passwords are hashed with **bcrypt** (cost 12); plain passwords and tokens are never stored or logged.
  Passwords need 8+ characters with a letter and a number (max 72 bytes, a bcrypt limit).
- Sessions are 60-minute JWTs in an **HttpOnly, SameSite=Lax** cookie, so page scripts cannot read them and
  other sites cannot make the browser send them on form posts. Logout revokes the token until it expires.
- Failed sign-ins: 5 per 15 minutes per email **and** per IP address, then HTTP 429. The same message is shown
  for a wrong password and an unknown email, so the form does not reveal which accounts exist.
- The revocation list and the rate-limit counters live **in memory**: they reset when the backend restarts and
  are not shared between several backend processes.
- **Not implemented:** password reset by email, email verification, multi-factor authentication, roles, OAuth.
  An administrator can reset a password only by deleting the user record (`users.json` or the `users` table).
- This is a local / demo-grade setup. For any deployment other people can reach: serve over **HTTPS**, set
  `COOKIE_SECURE=true`, `RIQ_ENV=production`, a strong `JWT_SECRET`, `ALLOW_REGISTRATION` as needed, no demo
  account, and restrict `CORS_ORIGINS` to your real frontend URL.
- Analysis settings (Settings page thresholds) are shared by all accounts; datasets are not.

## Upload capacity (no fixed size limit)

RestaurantIQ has **no application-level file-size limit** (the former 50 MB cap was removed from the frontend
and backend; a regression test uploads a ~55 MB CSV). Uploads are streamed to disk in 1 MB blocks, CSVs are read
in 100,000-row chunks and XLSX row by row. Capacity is still not unlimited:

- **Memory:** the cleaned dataset is held in memory for analysis (roughly 5-10x the CSV size for wide text files).
- **Disk:** each upload keeps the original file plus a cleaned copy per imported version.
- **Time:** very large files take longer to profile and import; the UI shows progress honestly.
- **Format:** XLSX parsing needs far more memory than the same data as CSV; convert huge workbooks to CSV.
- **Proxies:** a reverse proxy in front of the API (e.g. nginx `client_max_body_size`) may impose its own limit;
  the app reports a 413 from such a proxy as a server/proxy limit, not a RestaurantIQ limit.

Files are never silently truncated: malformed files are rejected with the reason, and every import shows a
balanced row reconciliation.

## Features

- Dataset-agnostic import with schema discovery, editable mapping, confidence/reason per column, capability profile
- Cleaning rules 1-9 with reconciliation, per-column completeness/uniqueness/validity and a transformation log
- Immutable dataset versions with a version selector; raw and cleaned downloads
- Dashboard: 9 KPIs, 8 charts/tables, outlier impact, Key Findings tagged Descriptive / Statistical / Suggestion
- Explorer: search, all filters, 5 sort keys, server-side pagination (50/page), table/grid views, detail drawer
- Market Analysis: popularity, density, price tiers, LQ heatmap, gaps, types by tier, Opportunity Score with
  sliders and sensitivity, Spearman and Mann-Whitney
- Compare 2-4 restaurants, cuisines or locations; AI Analyst for the six business questions
- SQL Playground (read-only, 5 s timeout, 1,000-row cap, schema browser, 5 analyst queries, CSV export)
- Reports (PDF with charts; executive or detailed; full or filtered) and BI exports (flat CSV, star schema)
- Light / Dark / System themes, responsive layout with a mobile drawer, keyboard-accessible controls

## Screenshot checklist

Capture these in both Light and Dark mode for the portfolio:

1. Dashboard with sample data (KPI row + charts)
2. Dashboard with a filter applied and the Show calculation dialog (PASS banner, SQL tab)
3. Data page: upload preview + column mapping + reconciliation
4. Explorer with the detail drawer open
5. Market Analysis: heatmap and Opportunity Score with sensitivity view
6. Statistical tests card
7. Compare (cuisines) with grouped bars
8. AI Analyst answering a business question (Demo Mode label visible)
9. SQL Playground with results
10. Reports preview and the first page of the PDF
11. Mobile width (390 px) with the navigation drawer open

## Limitations

See `docs/assumptions_log.md` and the Methodology page. In short: snapshot listing data; ratings are platform
scores, not revenue/footfall/profit; costs are approximate listed prices; all findings are observational;
the demo dataset is synthetic. Authentication is local/demo grade — see *Security notes and limitations*.

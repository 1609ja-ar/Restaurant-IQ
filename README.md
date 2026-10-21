# RestaurantIQ

**Turn Restaurant Data Into Smarter Business Decisions.**

RestaurantIQ is a portfolio analytics product that imports any reasonably structured restaurant dataset (CSV or
XLSX), cleans it with documented and tested rules, and turns it into KPIs, market analysis, statistical tests,
comparisons, an AI-assisted analyst, PDF reports and BI exports. Every number is computed by the backend from the
active dataset version, and every KPI or chart can show its real pandas code and the DuckDB SQL that reproduces it.

## Architecture

```
restaurantiq/
  backend/                 FastAPI + pandas + DuckDB (Python 3.11)
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
      store.py             raw uploads, immutable dataset versions, settings
    tests/                 pytest suite (cleaning rules, KPI hand calculations, pandas-vs-DuckDB, API, scale)
  frontend/                React 18 + Vite + TypeScript + Tailwind 3 + Recharts + React Query
    src/pages/             Dashboard, Explorer, Market Analysis, Compare, SQL Playground, AI Analyst,
                           Reports, Data, Methodology, Settings
    src/components/        app shell, filter bar, KPI cards, charts, Show calculation dialog, UI primitives
    src/lib/               API client, formatting, theme logic (+ vitest unit tests)
  notebooks/validation.ipynb   independent re-implementation of cleaning/KPIs vs the API (PASS/FAIL)
  docs/                    kpi_definitions.md, data_dictionary.md, assumptions_log.md
```

Data flow: **upload → profile & suggested mapping → user-confirmed mapping → quality check → import (new version)
→ analysis context (cached per version + settings) → filtered analytics / SQL / reports / exports**.

## Setup and run (Windows PowerShell)

Prerequisites: Python 3.11, Node.js 18+.

**Terminal 1 - backend** (port 8010; port 8000 may be blocked on some Windows PCs):

```powershell
cd "C:\Users\jaide\Desktop\Data prj\restaurantiq\backend"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

- Health: <http://127.0.0.1:8010/api/health> returns `{"status":"ok"}`
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
| `ANTHROPIC_API_KEY` | Enables live AI explanations in AI Analyst. Without it the analyst runs in labeled **Demo Mode**. | unset |
| `RIQ_LLM_MODEL` | Claude model used to explain computed results | `claude-opus-5-5` |
| `RIQ_DATA_DIR` | Where raw uploads, dataset versions and settings are stored | `backend/data` |

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
the demo dataset is synthetic. There is no authentication (single-user local app).

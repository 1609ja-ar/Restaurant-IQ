"""RestaurantIQ API (FastAPI).

Run from the backend folder:
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8010

All errors are returned as {"error": "<friendly explanation>"}; stack traces are only
written to the server log. There is no application-level upload size limit: practical
limits are RAM, disk space and processing time (see README "Upload capacity").
"""
from __future__ import annotations

import io
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import calculations as calc
from . import ingest, insights, kpis, sql_queries, stats
from .cleaning import CleanSettings, clean_dataset
from .demo_data import DEMO_MAPPING, demo_csv_bytes, generate_demo_dataframe
from .env import load_env
from .kpis import Filters, apply_filters, build_context
from .schemas import (ActiveDatasetRequest, AskRequest, CompareRequest, ImportSettings, ReportRequest,
                      SettingsUpdate, SqlRequest)
from .store import NotFound, Store

load_env()
log = logging.getLogger("restaurantiq")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="RestaurantIQ API", version="1.0.0",
              description="Turn Restaurant Data Into Smarter Business Decisions.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])

store = Store()
_ctx_cache: OrderedDict[tuple, kpis.Context] = OrderedDict()
_ctx_lock = threading.Lock()


class UserError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Error handling: friendly JSON, never a stack trace
# ---------------------------------------------------------------------------
@app.exception_handler(UserError)
async def _user_error(_: Request, exc: UserError):
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse({"error": str(exc)}, status_code=404)


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
        parts.append(f"{loc}: {err.get('msg')}" if loc else err.get("msg", "invalid value"))
    return JSONResponse({"error": "Invalid request - " + "; ".join(parts)}, status_code=422)


@app.exception_handler(MemoryError)
async def _memory_error(_: Request, exc: MemoryError):
    log.exception("Out of memory while processing a request")
    return JSONResponse({"error": "The server ran out of memory while processing this data. Try a smaller file, "
                                  "remove unused columns, or run the backend on a machine with more RAM."},
                        status_code=507)


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"error": "Something went wrong on the server while processing your request. "
                                  "Please try again; if it persists, check the backend log."}, status_code=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_ctx(dataset_id: Optional[str]) -> kpis.Context:
    ds = store.resolve(dataset_id)
    settings = store.settings()
    key = (ds, settings["revision"])
    with _ctx_lock:
        if key in _ctx_cache:
            _ctx_cache.move_to_end(key)
            return _ctx_cache[key]
    ctx = build_context(ds, store.load_cleaned(ds), store.dataset_meta(ds), settings)
    with _ctx_lock:
        _ctx_cache[key] = ctx
        while len(_ctx_cache) > 4:
            _ctx_cache.popitem(last=False)
    return ctx


def filter_params(
    location: list[str] = Query(default=[]), cuisine: list[str] = Query(default=[]),
    restaurant_type: list[str] = Query(default=[]), price_tier: list[str] = Query(default=[]),
    rating_min: Optional[float] = Query(default=None, ge=0, le=5),
    rating_max: Optional[float] = Query(default=None, ge=0, le=5),
    online_order: Optional[bool] = None, table_booking: Optional[bool] = None,
    currency: Optional[str] = None, search: Optional[str] = Query(default=None, max_length=200),
    exclude_outliers: bool = False,
) -> Filters:
    return Filters(location=location, cuisine=cuisine, restaurant_type=restaurant_type, price_tier=price_tier,
                   rating_min=rating_min, rating_max=rating_max, online_order=online_order,
                   table_booking=table_booking, currency=currency or None, search=(search or "").strip() or None,
                   exclude_outliers=exclude_outliers)


def context_block(ctx: kpis.Context, f: Filters, df: pd.DataFrame) -> dict:
    return {"dataset_id": ctx.dataset_id, "dataset_name": ctx.meta.get("name"), "version": ctx.meta.get("version"),
            "is_demo": ctx.meta.get("is_demo", False), "filters": f.describe(), "sample_size": len(df),
            "total_rows": len(ctx.frame), "settings": {k: ctx.settings[k] for k in ("min_group_n", "opportunity_min_n")},
            "prior": ctx.prior, "price_unit": ctx.meta.get("price_unit"),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def dataset_summary(meta: dict) -> dict:
    keys = ("dataset_id", "version", "name", "is_demo", "created_at", "source_filename", "source_upload_id",
            "reconciliation", "capabilities", "rating_scale", "price_unit", "currencies", "file_type")
    return {k: meta.get(k) for k in keys}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/schema/fields")
def canonical_fields():
    from .schemas import CANONICAL_FIELDS
    return {"fields": [{"field": k, "label": v["label"], "kind": v["kind"]} for k, v in CANONICAL_FIELDS.items()]}


# ---------------------------------------------------------------------------
# Datasets and versions
# ---------------------------------------------------------------------------
@app.get("/api/datasets")
def list_datasets():
    return {"active": store.active_id(), "versions": store.list_datasets()}


@app.get("/api/datasets/active")
def active_dataset():
    ds = store.active_id()
    return {"active": dataset_summary(store.dataset_meta(ds)) if ds else None}


@app.put("/api/datasets/active")
def set_active(req: ActiveDatasetRequest):
    store.set_active(req.dataset_id)
    return {"active": dataset_summary(store.dataset_meta(req.dataset_id))}


@app.get("/api/datasets/{dataset_id}")
def dataset_detail(dataset_id: str):
    meta = store.dataset_meta(dataset_id)
    return {**meta, "settings_used": store.settings()}


@app.get("/api/datasets/{dataset_id}/outlier-impact")
def outlier_impact(dataset_id: str, f: Filters = Depends(filter_params)):
    ctx = get_ctx(dataset_id)
    return {"impact": kpis.cost_outlier_impact(ctx, f)}


@app.get("/api/datasets/{dataset_id}/raw")
def download_raw(dataset_id: str):
    meta = store.dataset_meta(dataset_id)
    if meta.get("is_demo"):
        return Response(demo_csv_bytes(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="restaurantiq_sample_raw.csv"'})
    path = store.upload_path(meta["source_upload_id"])
    return FileResponse(path, filename=meta.get("source_filename") or path.name)


def cleaned_export_frame(cleaned: pd.DataFrame) -> pd.DataFrame:
    out = cleaned.copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, list)).any():
            out[col] = out[col].map(lambda v: ", ".join(v) if isinstance(v, list) else v)
    return out


def csv_response(frame: pd.DataFrame, filename: str) -> StreamingResponse:
    def gen():
        buf = io.StringIO()
        frame.head(0).to_csv(buf, index=False)
        yield buf.getvalue()
        for start in range(0, len(frame), 20_000):
            buf = io.StringIO()
            frame.iloc[start:start + 20_000].to_csv(buf, index=False, header=False)
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/datasets/{dataset_id}/cleaned.csv")
def download_cleaned(dataset_id: str):
    meta = store.dataset_meta(dataset_id)
    frame = cleaned_export_frame(store.load_cleaned(dataset_id))
    return csv_response(frame, f"restaurantiq_{dataset_id}_cleaned.csv")


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------
@app.get("/api/demo/sample.csv")
def demo_sample():
    return Response(demo_csv_bytes(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="restaurantiq_sample_data.csv"'})


@app.post("/api/demo/load")
def load_demo():
    raw = generate_demo_dataframe()
    settings = ImportSettings(mapping=[{"source_column": c, "canonical_field": DEMO_MAPPING.get(c)} for c in raw.columns],
                              dataset_name="Sample data — illustrative only", rating_scale_max=5, currency="INR",
                              price_unit="for_two")
    meta = _run_import(raw, settings, source={"is_demo": True, "source_filename": "restaurantiq_sample_data.csv",
                                              "file_type": "csv"})
    return {"active": dataset_summary(meta)}


# ---------------------------------------------------------------------------
# Upload -> profile -> validate -> import
# ---------------------------------------------------------------------------
@app.post("/api/uploads")
def upload_file(file: UploadFile = File(...)):
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in ingest.SUPPORTED_EXTENSIONS:
        raise UserError(f"Unsupported file type '.{ext}'. Please upload a .csv or .xlsx file." if ext else
                        "The file has no extension. Please upload a .csv or .xlsx file.", 415)
    upload_id, path = store.save_upload(file.file, filename)
    try:
        profile = ingest.profile_file(path, filename)
    except ingest.IngestError as exc:
        store.delete_upload(upload_id)
        raise UserError(str(exc), 422)
    except MemoryError:
        store.delete_upload(upload_id)
        raise
    except Exception:
        store.delete_upload(upload_id)
        log.exception("Failed to profile upload %s", filename)
        raise UserError("The file could not be processed. It may be corrupted or in an unexpected format. "
                        "Check that it opens correctly in a spreadsheet program and try again.", 422)
    store.update_upload_meta(upload_id, profile_summary={"row_count": profile["row_count"],
                                                         "column_count": profile["column_count"]})
    meta = store.upload_meta(upload_id)
    return {"upload_id": upload_id, "filename": filename, "size_bytes": meta["size_bytes"], "profile": profile}


def _load_upload_frame(upload_id: str) -> tuple[pd.DataFrame, dict]:
    meta = store.upload_meta(upload_id)
    path = store.upload_path(upload_id)
    try:
        fmt = ingest.detect_format(path, meta["filename"])
        return ingest.read_full(path, fmt), meta
    except ingest.IngestError as exc:
        raise UserError(str(exc), 422)


def _clean_settings(raw: pd.DataFrame, settings: ImportSettings) -> CleanSettings:
    mapping = {m.source_column: m.canonical_field for m in settings.mapping if m.canonical_field}
    missing = [c for c in mapping if c not in raw.columns]
    if missing:
        raise UserError(f"Mapped column(s) not found in the file: {', '.join(missing)}.", 422)
    fields = set(mapping.values())
    if len(fields & ingest.RESTAURANT_SIGNAL_FIELDS) < 2:
        raise UserError("This file does not look like restaurant data: map at least two of restaurant name, "
                        "cuisine, type, rating, cost, votes, location or online-order/booking columns, "
                        "or choose another file.", 422)
    scale_max = settings.rating_scale_max
    if "rating" in fields and scale_max is None:
        src = next(s for s, d in mapping.items() if d == "rating")
        inferred = ingest.infer_rating_scale(raw[src])
        scale_max = inferred["max"]
        if scale_max is None:
            raise UserError("The rating scale could not be determined. Set the rating scale maximum "
                            "(for example 5, 10 or 100) before importing.", 422)
    return CleanSettings(mapping=mapping, rating_scale_min=settings.rating_scale_min, rating_scale_max=scale_max,
                         currency=settings.currency, price_unit=settings.price_unit)


def _clean(raw: pd.DataFrame, settings: ImportSettings):
    cs = _clean_settings(raw, settings)
    try:
        return clean_dataset(raw, cs), cs
    except ValueError as exc:
        raise UserError(str(exc), 422)


def _run_import(raw: pd.DataFrame, settings: ImportSettings, source: dict) -> dict:
    result, cs = _clean(raw, settings)
    capabilities = kpis.capability_profile(build_context("tmp", result.cleaned, result.metadata, store.settings()).frame,
                                           result.metadata)
    meta = {
        "name": settings.dataset_name or source.get("source_filename") or "Imported dataset",
        **source,
        **result.metadata,
        "import_settings": settings.model_dump(),
        "reconciliation": result.reconciliation,
        "quality": result.quality,
        "log": result.log,
        "capabilities": capabilities,
        "columns": list(result.cleaned.columns),
    }
    return store.create_dataset(result.cleaned, meta)


@app.post("/api/uploads/{upload_id}/validate")
def validate_upload(upload_id: str, settings: ImportSettings):
    raw, _ = _load_upload_frame(upload_id)
    result, cs = _clean(raw, settings)
    ctx_frame = build_context("preview", result.cleaned, result.metadata, store.settings()).frame
    return {"reconciliation": result.reconciliation, "quality": result.quality, "log": result.log,
            "capabilities": kpis.capability_profile(ctx_frame, result.metadata),
            "rating_scale": result.metadata["rating_scale"], "price_tier_cutoffs": result.metadata["price_tier_cutoffs"],
            "currencies": result.metadata["currencies"]}


@app.post("/api/uploads/{upload_id}/import")
def import_upload(upload_id: str, settings: ImportSettings):
    raw, upload = _load_upload_frame(upload_id)
    meta = _run_import(raw, settings, source={"is_demo": False, "source_filename": upload["filename"],
                                              "source_upload_id": upload_id,
                                              "file_type": upload["filename"].rsplit(".", 1)[-1].lower()})
    return {"active": dataset_summary(meta)}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings():
    return store.settings()


@app.put("/api/settings")
def put_settings(req: SettingsUpdate):
    changes = {k: v for k, v in req.model_dump().items() if v is not None and k != "clear_bayes_m_override"}
    if req.clear_bayes_m_override:
        changes["bayes_m_override"] = None
    return store.update_settings(**changes)


# ---------------------------------------------------------------------------
# Dashboard, filters and calculations
# ---------------------------------------------------------------------------
@app.get("/api/filters/options")
def filters_options(dataset_id: Optional[str] = None):
    return kpis.filter_options(get_ctx(dataset_id))


DASHBOARD_CHARTS = ["top_cuisines", "by_location", "rating_distribution", "price_tiers", "wr_by_cuisine",
                    "median_cost_by_location", "rating_vs_votes", "distribution_profile"]


@app.get("/api/dashboard")
def dashboard(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params)):
    ctx = get_ctx(dataset_id)
    df = apply_filters(ctx, f)
    charts = {cid: {**calc.safe_run(ctx, cid, df), "label": calc.CALCS[cid].label,
                    "caveat": calc.CALCS[cid].caveat} for cid in DASHBOARD_CHARTS}
    return {"context": context_block(ctx, f, df), "kpis": calc.kpi_cards(ctx, df), "charts": charts,
            "cost_unit": calc.cost_unit(ctx, df), "findings": insights.key_findings(ctx, df),
            "outlier_impact": kpis.cost_outlier_impact(ctx, f) if ctx.capabilities["fields"]["cost"] else None,
            "capabilities": ctx.capabilities}


def weight_params(w_rating: Optional[float] = Query(default=None, ge=0),
                  w_engagement: Optional[float] = Query(default=None, ge=0),
                  w_low_saturation: Optional[float] = Query(default=None, ge=0)) -> Optional[dict]:
    if w_rating is None and w_engagement is None and w_low_saturation is None:
        return None
    return {"rating": w_rating or 0, "engagement": w_engagement or 0, "low_saturation": w_low_saturation or 0}


@app.get("/api/calculations/{calc_id}")
def show_calculation(calc_id: str, dataset_id: Optional[str] = None, f: Filters = Depends(filter_params),
                     weights: Optional[dict] = Depends(weight_params)):
    if calc_id not in calc.CALCS:
        raise UserError(f"Unknown calculation '{calc_id}'.", 404)
    ctx = get_ctx(dataset_id)
    params = {"weights": weights} if calc_id == "opportunity" and weights else {}
    return calc.show_calculation(ctx, calc_id, f, **params)


# ---------------------------------------------------------------------------
# Explorer
# ---------------------------------------------------------------------------
SORTABLE = {"rating": "rating", "weighted_rating": "weighted_rating", "votes": "review_count",
            "name": "restaurant_name", "cost": "cost"}
LIST_COLUMNS = ["rid", "restaurant_name", "location", "cuisines", "restaurant_type", "rating", "weighted_rating",
                "review_count", "cost", "currency", "price_tier", "online_order", "table_booking", "is_unrated",
                "cost_outlier"]


@app.get("/api/restaurants")
def list_restaurants(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params),
                     sort: str = Query(default="weighted_rating"), order: str = Query(default="desc"),
                     page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100)):
    if sort not in SORTABLE:
        raise UserError(f"Cannot sort by '{sort}'. Choose one of: {', '.join(SORTABLE)}.", 422)
    ctx = get_ctx(dataset_id)
    df = apply_filters(ctx, f)
    col = SORTABLE[sort]
    ascending = order == "asc"
    # Case-insensitive name sort; nulls always last; rid breaks ties so pages are stable.
    sort_values = df[col].str.lower() if col == "restaurant_name" else df[col]
    ordered = (df.assign(_sort=sort_values)
               .sort_values(["_sort", "rid"], ascending=[ascending, True], na_position="last", kind="mergesort")
               .drop(columns="_sort"))
    total = len(ordered)
    pages = max(1, -(-total // page_size))
    page = min(page, pages)
    rows = ordered.iloc[(page - 1) * page_size: page * page_size]
    items = kpis._records(rows[[c for c in LIST_COLUMNS if c in rows]])
    return {"context": context_block(ctx, f, df), "total": total, "page": page, "pages": pages,
            "page_size": page_size, "sort": sort, "order": "asc" if ascending else "desc", "items": items}


@app.get("/api/restaurants/{rid}")
def restaurant_detail(rid: int, dataset_id: Optional[str] = None):
    ds = store.resolve(dataset_id)
    cleaned = store.load_cleaned(ds)
    row = cleaned[cleaned["rid"] == rid]
    if row.empty:
        raise UserError("Restaurant not found in this dataset version.", 404)
    ctx = get_ctx(ds)
    record = kpis._records(row)[0]
    in_analysis = ctx.frame[ctx.frame["rid"] == rid]
    record["weighted_rating"] = (None if in_analysis.empty or pd.isna(in_analysis["weighted_rating"].iloc[0])
                                 else float(in_analysis["weighted_rating"].iloc[0]))
    meta = store.dataset_meta(ds)
    return {"restaurant": record, "extras": meta.get("extras", []), "prior": ctx.prior}


# ---------------------------------------------------------------------------
# Market analysis and statistics
# ---------------------------------------------------------------------------
@app.get("/api/market")
def market(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params),
           weights: Optional[dict] = Depends(weight_params), focus_cuisine: Optional[str] = None):
    ctx = get_ctx(dataset_id)
    df = apply_filters(ctx, f)
    out = {"context": context_block(ctx, f, df), "capabilities": ctx.capabilities}
    for cid in ("cuisine_popularity", "location_density", "price_tier_analysis", "market_gaps", "types_by_tier",
                "spearman", "mann_whitney"):
        out[cid] = {**calc.safe_run(ctx, cid, df), "label": calc.CALCS[cid].label, "caveat": calc.CALCS[cid].caveat}
    opp = calc.safe_run(ctx, "opportunity", df, **({"weights": weights} if weights else {}))
    out["opportunity"] = {**opp, "weights": stats.normalize_weights(weights), "label": calc.CALCS["opportunity"].label,
                          "min_n": ctx.settings["opportunity_min_n"]}
    sat = calc.safe_run(ctx, "saturation", df)
    out["heatmap"] = {**sat, "data": stats.heatmap_view(df, ctx) if sat["available"] else None}
    out["sensitivity"] = (stats.opportunity_sensitivity(df, ctx) if opp["available"] else None)
    out["focus_cuisine"] = stats.cuisine_share_by_location(df, ctx, focus_cuisine) if focus_cuisine else None
    return out


# ---------------------------------------------------------------------------
# SQL Playground
# ---------------------------------------------------------------------------
@app.get("/api/sql/schema")
def sql_schema(dataset_id: Optional[str] = None):
    return {"tables": sql_queries.schema(get_ctx(dataset_id)), "examples": sql_queries.PREBUILT_QUERIES,
            "limits": {"timeout_seconds": sql_queries.SQL_TIMEOUT_SECONDS, "max_rows": sql_queries.SQL_MAX_ROWS}}


@app.post("/api/sql")
def run_sql(req: SqlRequest):
    ctx = get_ctx(req.dataset_id)
    try:
        return sql_queries.run_playground(ctx, req.sql)
    except sql_queries.SqlError as exc:
        raise UserError(str(exc), 400)


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------
@app.get("/api/compare/search")
def compare_search(dataset_id: Optional[str] = None, q: str = Query(default="", max_length=100)):
    """Restaurant picker for Compare: name contains q (case-insensitive), top 20 by votes."""
    ctx = get_ctx(dataset_id)
    df = ctx.frame
    if q.strip():
        df = df[df["restaurant_name"].str.contains(q.strip(), case=False, regex=False, na=False)]
    df = df.sort_values(["review_count", "rid"], ascending=[False, True], na_position="last").head(20)
    return {"items": kpis._records(df[["rid", "restaurant_name", "location", "rating", "review_count"]])}


@app.post("/api/compare")
def compare_items(req: CompareRequest):
    from .compare import compare
    ctx = get_ctx(req.dataset_id)
    if len(set(req.items)) != len(req.items):
        raise UserError("Choose different items to compare (duplicates found).", 422)
    try:
        return {**compare(ctx, req.kind, req.items), "context": context_block(ctx, Filters(), ctx.frame)}
    except ValueError as exc:
        raise UserError(str(exc), 422)


# ---------------------------------------------------------------------------
# AI Analyst
# ---------------------------------------------------------------------------
@app.get("/api/export/filtered.csv")
def export_filtered(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params)):
    from . import exports
    ctx = get_ctx(dataset_id)
    return csv_response(exports.filtered_csv(ctx, f), f"restaurantiq_{ctx.dataset_id}_filtered.csv")


@app.get("/api/export/bi-flat.csv")
def export_bi_flat(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params)):
    from . import exports
    ctx = get_ctx(dataset_id)
    return csv_response(exports.bi_flat(ctx, f), f"restaurantiq_{ctx.dataset_id}_bi_flat.csv")


@app.get("/api/export/star-schema.zip")
def export_star(dataset_id: Optional[str] = None, f: Filters = Depends(filter_params)):
    from . import exports
    ctx = get_ctx(dataset_id)
    return Response(exports.star_schema_zip(ctx, f), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="restaurantiq_{ctx.dataset_id}_star_schema.zip"'})


def _report(req: ReportRequest) -> dict:
    from .reports import build_report
    ctx = get_ctx(req.dataset_id)
    f = Filters.from_dict(req.filters) if req.use_filters else Filters()
    if req.report_type == "comparison" and (not req.compare_kind or len(req.compare_items) < 2):
        raise UserError("A comparison report needs a comparison type and at least two items.", 422)
    if req.report_type in ("cuisine", "location") and not req.focus:
        raise UserError(f"Choose a {req.report_type} for this report.", 422)
    try:
        return build_report(ctx, req.report_type, req.length, f, req.focus, req.compare_kind, req.compare_items)
    except ValueError as exc:
        raise UserError(str(exc), 422)


@app.post("/api/reports/preview")
def report_preview(req: ReportRequest):
    return _report(req)


@app.post("/api/reports/pdf")
def report_pdf(req: ReportRequest):
    from .reports import render_pdf
    report = _report(req)
    pdf = render_pdf(report)
    name = f"restaurantiq_{report['dataset']['id']}_{req.report_type}_{req.length}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/analyst/suggestions")
def analyst_suggestions():
    from . import analyst
    return {"suggestions": analyst.SUGGESTED, "mode": analyst.mode()}


@app.post("/api/analyst/ask")
def analyst_ask(req: AskRequest, intent: Optional[str] = None):
    from . import analyst
    ctx = get_ctx(req.dataset_id)
    return analyst.ask(ctx, req.question, location=req.location, intent_hint=intent)

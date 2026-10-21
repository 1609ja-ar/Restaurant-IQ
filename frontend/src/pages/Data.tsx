import { useCallback, useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight, CheckCircle2, Download, FileSpreadsheet, FlaskConical, Loader2, RefreshCw, Upload, XCircle,
} from "lucide-react";
import { api, ApiError, downloadUrl, uploadFile } from "../lib/api";
import { useActiveDataset, useLoadDemo, useSetActive, useVersions } from "../hooks/useDataset";
import { useToast } from "../hooks/useToast";
import { fmtBytes, fmtDate, fmtInt, fmtPct } from "../lib/format";
import type { Capabilities, DatasetDetail, MappingSuggestion, QualityRow, Reconciliation, UploadResponse, ValidateResponse, LogEntry } from "../lib/types";
import { Assumptions, Card, ErrorState, Note, PageHeader, SampleBadge, SectionTitle, Skeleton, Spinner } from "../components/ui";

const ACCEPTED = [".csv", ".xlsx"];

interface FieldDef { field: string; label: string; kind: string }

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; file: File; progress: number }
  | { phase: "processing"; file: File }
  | { phase: "ready"; file: File; data: UploadResponse }
  | { phase: "error"; file?: File; message: string };

export default function DataPage() {
  const active = useActiveDataset();
  const toast = useToast();
  const loadDemo = useLoadDemo();
  const [upload, setUpload] = useState<UploadState>({ phase: "idle" });

  const onDemo = () => loadDemo.mutate(undefined, {
    onSuccess: (r) => toast("success", "Sample dataset loaded", `${r.active.name} is now active as ${r.active.dataset_id}.`),
    onError: (e) => toast("error", "Could not load the sample dataset", (e as Error).message),
  });

  return (
    <>
      <PageHeader title="Data" description="Upload a restaurant dataset, review the column mapping and data quality, then import it as a new version. The original file is never modified."
        actions={<>
          <a className="btn-secondary" href={downloadUrl("/demo/sample.csv")} download><Download className="h-4 w-4" aria-hidden /> Download Sample CSV</a>
          <button className="btn-primary" onClick={onDemo} disabled={loadDemo.isPending}>
            {loadDemo.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FlaskConical className="h-4 w-4" aria-hidden />} Load Demo Dataset
          </button>
        </>} />

      <Stepper upload={upload} />
      <UploadArea state={upload} setState={setUpload} />
      {upload.phase === "ready" && <ImportWizard key={upload.data.upload_id} data={upload.data} onDone={() => setUpload({ phase: "idle" })} />}

      <SectionTitle>Dataset versions</SectionTitle>
      <VersionsPanel />

      {active.data && <ActiveDatasetReport datasetId={active.data.dataset_id} />}
      {active.isLoading && <Skeleton className="h-64" />}

      <Assumptions items={[
        "Supported formats: CSV (comma, semicolon, tab or pipe separated; UTF-8 preferred) and XLSX (first sheet with data).",
        "There is no fixed file-size limit in RestaurantIQ. Practical limits are the backend machine's memory, free disk space and processing time; very large XLSX files need much more memory than the same data as CSV.",
        "Malformed files are rejected with the reason; rows are never silently dropped or truncated.",
        "Empty or whitespace-only cells are treated as missing values (null), never as zero or 'No'.",
        "Duplicates are identified by normalized restaurant name + address; the listing with the most votes is kept.",
        "Every import creates a new dataset version; previous versions remain available.",
      ]} />
    </>
  );
}

function Stepper({ upload }: { upload: UploadState }) {
  const step = upload.phase === "ready" ? 2 : upload.phase === "uploading" || upload.phase === "processing" ? 1 : 0;
  const steps = ["Select file", "Upload & inspect", "Map columns & check quality", "Confirm import"];
  return (
    <ol className="mb-4 hidden flex-wrap items-center gap-2 text-xs md:flex" aria-label="Import steps">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={`flex h-5 w-5 items-center justify-center rounded-full text-2xs font-semibold ${i <= step ? "bg-accent text-on-accent" : "bg-surface-3 text-subtle"}`}>{i + 1}</span>
          <span className={i <= step ? "font-medium text-ink" : "text-subtle"}>{s}</span>
          {i < steps.length - 1 && <ArrowRight className="h-3 w-3 text-subtle" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

function UploadArea({ state, setState }: { state: UploadState; setState: (s: UploadState) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const busy = state.phase === "uploading" || state.phase === "processing";

  const start = useCallback(async (file: File) => {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      setState({ phase: "error", file, message: `"${file.name}" is not a CSV or XLSX file. Please choose a .csv or .xlsx file.` });
      return;
    }
    if (file.size === 0) {
      setState({ phase: "error", file, message: "The selected file is empty." });
      return;
    }
    setState({ phase: "uploading", file, progress: 0 });
    try {
      const data = await uploadFile<UploadResponse>(file, (p) => {
        if (p >= 1) setState({ phase: "processing", file });
        else setState({ phase: "uploading", file, progress: p });
      });
      setState({ phase: "ready", file, data });
    } catch (e) {
      setState({ phase: "error", file, message: e instanceof ApiError ? e.message : "Upload failed." });
    }
  }, [setState]);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (busy) return;
    const f = e.dataTransfer.files?.[0];
    if (f) start(f);
  };

  return (
    <div className="card p-4">
      <div onDragOver={(e) => { e.preventDefault(); if (!busy) setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
           className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${drag ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2"}`}>
        <div className="rounded-full bg-surface p-3 shadow-card"><Upload className="h-5 w-5 text-accent-ink" aria-hidden /></div>
        <div>
          <p className="text-base font-semibold text-ink">Upload your CSV or XLSX dataset</p>
          <p className="mt-1 text-sm text-muted">Select a file to begin data analysis.</p>
        </div>
        <input ref={input} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only"
               id="file-input" onChange={(e) => { const f = e.target.files?.[0]; if (f) start(f); e.target.value = ""; }} disabled={busy} />
        <label htmlFor="file-input" className={`btn-primary cursor-pointer ${busy ? "pointer-events-none opacity-50" : ""}`} tabIndex={0}
               onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}>
          <FileSpreadsheet className="h-4 w-4" aria-hidden /> Browse files
        </label>
        <p className="text-xs text-subtle">Supported: .csv, .xlsx. You can also drag and drop a file here.</p>
      </div>

      {state.phase === "uploading" && (
        <div className="mt-4" aria-live="polite">
          <div className="flex justify-between text-sm"><span className="truncate text-ink">Uploading {state.file.name}</span>
            <span className="tabular-nums text-muted">{Math.round(state.progress * 100)}% of {fmtBytes(state.file.size)}</span></div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuenow={Math.round(state.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
            <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${state.progress * 100}%` }} />
          </div>
        </div>
      )}
      {state.phase === "processing" && (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted" aria-live="polite">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Upload complete. Reading and profiling {state.file.name} on the server (large files can take a while)...
        </div>
      )}
      {state.phase === "error" && (
        <div className="mt-4 flex items-start gap-2 rounded-lg bg-danger-soft p-3 text-sm" role="alert">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          <div><p className="font-semibold text-ink">{state.file ? `Could not use ${state.file.name}` : "Upload failed"}</p><p className="text-muted">{state.message}</p></div>
        </div>
      )}
    </div>
  );
}

function ImportWizard({ data, onDone }: { data: UploadResponse; onDone: () => void }) {
  const p = data.profile;
  const toast = useToast();
  const qc = useQueryClient();
  const fields = useQuery({ queryKey: ["canonical-fields"], queryFn: () => api<{ fields: FieldDef[] }>("/schema/fields"), staleTime: Infinity });
  const [mapping, setMapping] = useState<Record<string, string>>(() =>
    Object.fromEntries(p.suggested_mapping.map((m) => [m.source_column, m.suggested_field ?? ""])));
  const [scale, setScale] = useState<string>(p.rating_scale?.max?.toString() ?? "");
  const [currency, setCurrency] = useState("");
  const [priceUnit, setPriceUnit] = useState(p.suggested_price_unit || "unknown");
  const [name, setName] = useState(data.filename.replace(/\.(csv|xlsx)$/i, ""));
  const [validated, setValidated] = useState<ValidateResponse | null>(null);

  const duplicates = Object.values(mapping).filter((v, i, a) => v && a.indexOf(v) !== i);
  const ratingMapped = Object.values(mapping).includes("rating");
  const costMapped = Object.values(mapping).includes("cost");
  const currencyMapped = Object.values(mapping).includes("currency");
  const body = () => ({
    mapping: Object.entries(mapping).map(([source_column, f]) => ({ source_column, canonical_field: f || null })),
    dataset_name: name.trim() || null,
    rating_scale_max: scale.trim() ? Number(scale) : null,
    currency: currency.trim().toUpperCase() || null,
    price_unit: priceUnit,
  });

  const validate = useMutation({
    mutationFn: () => api<ValidateResponse>(`/uploads/${data.upload_id}/validate`, { method: "POST", body: body() }),
    onSuccess: (r) => setValidated(r),
    onError: () => setValidated(null),
  });
  const doImport = useMutation({
    mutationFn: () => api<{ active: { dataset_id: string; name: string } }>(`/uploads/${data.upload_id}/import`, { method: "POST", body: body() }),
    onSuccess: (r) => {
      toast("success", "Import complete", `${r.active.name} is now active as ${r.active.dataset_id}.`);
      qc.invalidateQueries();
      onDone();
    },
    onError: (e) => toast("error", "Import failed", (e as Error).message),
  });
  const changeMapping = (col: string, v: string) => { setMapping((m) => ({ ...m, [col]: v })); setValidated(null); };
  const suggestion = (col: string): MappingSuggestion | undefined => p.suggested_mapping.find((m) => m.source_column === col);

  return (
    <div className="mt-6 space-y-4">
      <Card title={data.filename} subtitle={`${p.file_type.toUpperCase()} · ${fmtBytes(data.size_bytes)}${p.sheet ? ` · sheet "${p.sheet}"` : ""}${p.encoding ? ` · ${p.encoding === "utf-8-sig" ? "UTF-8" : p.encoding}` : ""}`}
            actions={<button className="btn-ghost btn-sm" onClick={onDone}>Cancel</button>}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Rows detected" value={fmtInt(p.row_count)} />
          <Stat label="Columns" value={fmtInt(p.column_count)} />
          <Stat label="Blank rows" value={fmtInt(p.blank_row_count)} />
          <Stat label="Mapped fields" value={fmtInt(Object.values(mapping).filter(Boolean).length)} />
        </div>
        {p.warnings.length > 0 && <div className="mt-3 space-y-2">{p.warnings.map((w) => <Note key={w} tone="warning">{w}</Note>)}</div>}
      </Card>

      <Card title="Preview" subtitle={`First ${p.preview.length} rows, exactly as read from the file (raw text)`} bodyClass="p-0">
        <div className="max-h-96 overflow-auto">
          <table className="table-base">
            <thead className="sticky top-0"><tr><th className="num">#</th>{p.columns.map((c) => <th key={c.name}>{c.name}</th>)}</tr></thead>
            <tbody>
              {p.preview.map((r, i) => (
                <tr key={i}><td className="num text-subtle">{i + 1}</td>
                  {p.columns.map((c) => <td key={c.name} className="max-w-[16rem] truncate" title={r[c.name] ?? "empty"}>
                    {r[c.name] ?? <span className="text-subtle">empty</span>}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Column mapping" subtitle="Suggestions are based on header names and sample values. Review every row; unmapped columns are preserved in the cleaned file." bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead><tr><th>Source column</th><th>Detected type</th><th className="num">Missing</th><th>Maps to</th><th>Why</th></tr></thead>
            <tbody>
              {p.columns.map((c) => {
                const s = suggestion(c.name);
                const dup = mapping[c.name] && duplicates.includes(mapping[c.name]);
                return (
                  <tr key={c.name}>
                    <td className="font-medium">{c.name}<p className="mt-0.5 max-w-[14rem] truncate text-xs font-normal text-subtle">{c.sample_values.slice(0, 3).join(" · ")}</p></td>
                    <td className="text-muted">{c.detected_type}</td>
                    <td className="num">{fmtPct(c.null_pct)}</td>
                    <td className="min-w-[13rem]">
                      <select aria-label={`Mapping for ${c.name}`} className={`input ${dup ? "border-danger" : ""}`} value={mapping[c.name] ?? ""} onChange={(e) => changeMapping(c.name, e.target.value)}>
                        <option value="">Leave unmapped (keep as extra)</option>
                        {(fields.data?.fields ?? []).map((f) => <option key={f.field} value={f.field}>{f.label}</option>)}
                      </select>
                      {dup && <p className="mt-1 text-xs text-danger">Mapped from more than one column.</p>}
                    </td>
                    <td className="max-w-[22rem] text-xs text-muted">
                      {s?.confidence && <span className={`mr-1 rounded px-1 font-semibold ${s.confidence === "high" ? "bg-success-soft text-success" : "bg-warning-soft text-warning"}`}>{s.confidence}</span>}
                      {s?.reason}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="grid gap-3 border-t border-line p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div><label className="label" htmlFor="ds-name">Dataset name</label><input id="ds-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div>
            <label className="label" htmlFor="scale">Rating scale maximum</label>
            <input id="scale" className="input" inputMode="decimal" value={scale} onChange={(e) => { setScale(e.target.value); setValidated(null); }} disabled={!ratingMapped} placeholder="e.g. 5, 10 or 100" />
            <p className="mt-1 text-xs text-subtle">{ratingMapped ? (p.rating_scale?.source ?? "Set the scale of the source ratings.") : "Map a rating column to set its scale."} Ratings are normalized to 0–5.</p>
          </div>
          <div>
            <label className="label" htmlFor="currency">Currency (dataset level)</label>
            <input id="currency" className="input" value={currency} onChange={(e) => { setCurrency(e.target.value); setValidated(null); }} disabled={!costMapped || currencyMapped} placeholder={currencyMapped ? "From currency column" : "e.g. INR, USD"} maxLength={8} />
            <p className="mt-1 text-xs text-subtle">Leave blank if unknown; costs are then shown without a currency symbol.</p>
          </div>
          <div>
            <label className="label" htmlFor="unit">Cost refers to</label>
            <select id="unit" className="input" value={priceUnit} onChange={(e) => setPriceUnit(e.target.value)} disabled={!costMapped}>
              <option value="for_two">Cost for two people</option><option value="per_person">Cost per person</option>
              <option value="menu_item">Menu item price</option><option value="price_tier">Price tier / level</option><option value="unknown">Unknown</option>
            </select>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line p-4">
          <button className="btn-secondary" onClick={() => validate.mutate()} disabled={validate.isPending || duplicates.length > 0}>
            {validate.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <RefreshCw className="h-4 w-4" aria-hidden />} Check data quality
          </button>
          <button className="btn-primary" onClick={() => doImport.mutate()} disabled={!validated || doImport.isPending || duplicates.length > 0}>
            {doImport.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />} Confirm import as new version
          </button>
          {!validated && <span className="text-xs text-subtle">Run the quality check to review the result before importing.</span>}
          {doImport.isPending && <span className="text-xs text-muted">Cleaning and saving the full dataset...</span>}
        </div>
        {validate.isError && <div className="px-4 pb-4"><ErrorState error={validate.error} /></div>}
      </Card>

      {validated && (
        <div className="space-y-4">
          <ReconciliationView rec={validated.reconciliation} />
          <CapabilityView caps={validated.capabilities} />
          <QualityTable rows={validated.quality} />
          <LogView log={validated.log} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-surface-2 p-3"><p className="text-xs text-muted">{label}</p><p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</p></div>;
}

export function ReconciliationView({ rec }: { rec: Reconciliation }) {
  const steps = [
    { label: "Raw rows", value: rec.raw_rows, note: "Rows read from the file" },
    { label: "Blank rows removed", value: -rec.blank_rows_removed, note: "Every cell empty" },
    { label: "Duplicates removed", value: -rec.duplicates_removed, note: rec.dedup_rule },
    { label: "Invalid rows excluded", value: -rec.invalid_rows_excluded,
      note: `Rating outside scale ${rec.invalid_breakdown.rating_outside_scale}, negative votes ${rec.invalid_breakdown.negative_votes}, negative cost ${rec.invalid_breakdown.negative_cost} (a row can have several)` },
    { label: "Rows used in analysis", value: rec.rows_used_in_analysis, note: "De-duplicated, valid rows", total: true },
  ];
  return (
    <Card title="Row reconciliation" subtitle={rec.balanced ? "Balanced: raw - blank - duplicates - invalid = rows used" : "Warning: counts do not balance"}>
      <ol className="grid gap-2 md:grid-cols-5">
        {steps.map((s) => (
          <li key={s.label} className={`rounded-lg border p-3 ${s.total ? "border-accent/50 bg-accent-soft" : "border-line bg-surface-2"}`}>
            <p className="text-xs text-muted">{s.label}</p>
            <p className="text-xl font-semibold tabular-nums text-ink">{s.value < 0 ? `−${fmtInt(-s.value)}` : fmtInt(s.value)}</p>
            <p className="mt-1 text-xs leading-snug text-subtle">{s.note}</p>
          </li>
        ))}
      </ol>
      {rec.unrated_rows_in_analysis !== null && (
        <p className="mt-3 text-sm text-muted">Of the {fmtInt(rec.rows_used_in_analysis)} rows used, <span className="font-semibold text-ink">{fmtInt(rec.unrated_rows_in_analysis)}</span> are unrated:
          they stay in counts, cost and location analysis but are excluded from rating statistics ({fmtInt(rec.rated_rows_in_analysis)} rated rows).
          {rec.cost_outliers_flagged > 0 && ` ${fmtInt(rec.cost_outliers_flagged)} cost outliers are flagged but kept.`}</p>
      )}
      {rec.duplicate_examples.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Show duplicate pairs (source row numbers)</summary>
          <p className="mt-2 text-xs text-muted">{rec.duplicate_examples.slice(0, 30).map((d) => `row ${d.removed_source_row} → kept ${d.kept_source_row}`).join("; ")}</p>
        </details>
      )}
    </Card>
  );
}

export function CapabilityView({ caps }: { caps: Capabilities }) {
  const labels: Record<string, string> = {
    rating_analysis: "Rating analysis", weighted_rating: "Weighted (Bayesian) rating", cost_analysis: "Cost analysis",
    cuisine_analysis: "Cuisine analysis", location_analysis: "Location analysis", price_tiers: "Price tiers",
    online_order_test: "Online-order comparison", table_booking_test: "Table-booking comparison", map: "Map (coordinates)",
    time_trend: "Time trend", opportunity_score: "Opportunity Score",
  };
  return (
    <Card title="Analysis capability profile" subtitle="Features are enabled only when the mapped columns support them">
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(caps.features).map(([k, f]) => (
          <li key={k} className="flex items-start gap-2 text-sm">
            {f.available ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="Available" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-subtle" aria-label="Unavailable" />}
            <span><span className={f.available ? "text-ink" : "text-muted"}>{labels[k] ?? k}</span>
              {!f.available && <span className="block text-xs text-subtle">Needs {f.requires}</span>}</span>
          </li>
        ))}
      </ul>
      {caps.currencies.length > 1 && <div className="mt-3"><Note tone="warning">Mixed currencies ({caps.currencies.join(", ")}): cost metrics require a currency filter and are never combined.</Note></div>}
    </Card>
  );
}

export function QualityTable({ rows }: { rows: QualityRow[] }) {
  const bar = (v: number | null) => v === null ? <span className="text-subtle">N/A</span> : (
    <span className="flex items-center justify-end gap-2"><span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-surface-3 sm:block">
      <span className={`block h-full rounded-full ${v >= 95 ? "bg-success" : v >= 80 ? "bg-warning" : "bg-danger"}`} style={{ width: `${v}%` }} /></span>{fmtPct(v)}</span>);
  return (
    <Card title="Data quality by column" subtitle="Computed on de-duplicated rows. Completeness = non-empty; uniqueness = distinct / non-empty; validity = parseable and in range / non-empty" bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="table-base">
          <thead><tr><th>Column</th><th>Mapped to</th><th className="num">Completeness</th><th className="num">Uniqueness</th><th className="num">Validity</th><th>Rule</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.column}><td className="font-medium">{r.column}</td><td className="text-muted">{r.field ?? "extra (unmapped)"}</td>
              <td className="num">{bar(r.completeness_pct)}</td><td className="num">{fmtPct(r.uniqueness_pct)}</td><td className="num">{bar(r.validity_pct)}</td>
              <td className="max-w-xs text-xs text-subtle">{r.note}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </Card>
  );
}

function LogView({ log }: { log: LogEntry[] }) {
  return (
    <Card title="Transformation log" subtitle="Every cleaning action, in order, with the rows it affected">
      <ol className="space-y-2">
        {log.map((l, i) => (
          <li key={i} className="flex gap-3 text-sm">
            <span className="w-6 shrink-0 text-right tabular-nums text-subtle">{i + 1}.</span>
            <div className="min-w-0"><span className="font-medium text-ink">{l.step}</span><span className="text-muted">: {l.detail}</span></div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function VersionsPanel() {
  const versions = useVersions();
  const setActive = useSetActive();
  const toast = useToast();
  if (versions.isLoading) return <Skeleton className="h-24" />;
  if (versions.isError) return <ErrorState error={versions.error} onRetry={() => versions.refetch()} />;
  const rows = versions.data?.versions ?? [];
  if (!rows.length) return <Card><p className="text-sm text-muted">No versions yet. Load the demo dataset or import a file.</p></Card>;
  return (
    <Card bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="table-base">
          <thead><tr><th>Version</th><th>Name</th><th>Source</th><th className="num">Rows used</th><th>Created</th><th><span className="sr-only">Action</span></th></tr></thead>
          <tbody>
            {rows.map((v) => {
              const isActive = versions.data?.active === v.dataset_id;
              return (
                <tr key={v.dataset_id}>
                  <td className="font-semibold">{v.dataset_id}</td>
                  <td>{v.name} {v.is_demo && <span className="ml-1"><SampleBadge /></span>}</td>
                  <td className="text-muted">{v.source_filename ?? "N/A"}</td>
                  <td className="num">{fmtInt(v.rows_used)}</td>
                  <td className="whitespace-nowrap text-muted">{fmtDate(v.created_at)}</td>
                  <td className="text-right">
                    {isActive ? <span className="chip border-success/40 bg-success-soft text-success">Active</span> : (
                      <button className="btn-secondary btn-sm" disabled={setActive.isPending}
                              onClick={() => setActive.mutate(v.dataset_id, { onSuccess: () => toast("success", `Switched to ${v.dataset_id}`, "All pages now use this version."),
                                onError: (e) => toast("error", "Could not switch version", (e as Error).message) })}>Make active</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ActiveDatasetReport({ datasetId }: { datasetId: string }) {
  const q = useQuery({ queryKey: ["dataset-detail", datasetId], queryFn: () => api<DatasetDetail>(`/datasets/${datasetId}`) });
  if (q.isLoading) return <div className="mt-6"><Spinner label="Loading quality report" /></div>;
  if (q.isError) return <div className="mt-6"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data!;
  return (
    <>
      <SectionTitle hint={`${d.dataset_id} · imported ${fmtDate(d.created_at)}`}>Active dataset quality report</SectionTitle>
      <div className="mb-4 flex flex-wrap gap-2">
        <a className="btn-secondary" href={downloadUrl(`/datasets/${d.dataset_id}/cleaned.csv`)} download><Download className="h-4 w-4" aria-hidden /> Download cleaned CSV</a>
        <a className="btn-secondary" href={downloadUrl(`/datasets/${d.dataset_id}/raw`)} download><Download className="h-4 w-4" aria-hidden /> Download original (raw) file</a>
      </div>
      <div className="space-y-4">
        <ReconciliationView rec={d.reconciliation} />
        <CapabilityView caps={d.capabilities} />
        <QualityTable rows={d.quality} />
        <LogView log={d.log} />
        <Card title="Import settings" subtitle="Stored with the version so results are reproducible">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div><dt className="text-muted">Rating scale</dt><dd className="text-ink">{d.rating_scale.max ? `${d.rating_scale.min}–${d.rating_scale.max} (normalized to 0–5)` : "N/A"}</dd></div>
            <div><dt className="text-muted">Cost unit</dt><dd className="text-ink">{d.price_unit.replace("_", " ")}</dd></div>
            <div><dt className="text-muted">Currencies</dt><dd className="text-ink">{d.currencies.length ? d.currencies.join(", ") : "Unknown"}</dd></div>
            <div><dt className="text-muted">Location field used</dt><dd className="text-ink">{d.location_source ?? "N/A"}</dd></div>
            <div className="sm:col-span-2"><dt className="text-muted">Mapping</dt><dd className="text-ink">{Object.entries(d.mapping).map(([s, f]) => `${s} → ${f}`).join(", ")}</dd></div>
            <div className="sm:col-span-2"><dt className="text-muted">Preserved extra columns</dt><dd className="text-ink">{d.extras.length ? d.extras.join(", ") : "None"}</dd></div>
          </dl>
        </Card>
      </div>
    </>
  );
}

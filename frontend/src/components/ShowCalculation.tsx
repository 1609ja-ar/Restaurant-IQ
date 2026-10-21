import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Code2, XCircle } from "lucide-react";
import { analysisParams, api, type Params } from "../lib/api";
import type { Filters } from "../lib/filters";
import type { CalculationDetail } from "../lib/types";
import { Dialog, ErrorState, Note, Segmented, Spinner } from "./ui";

/** "Show calculation": the real pandas source, the exact DuckDB SQL that was executed with the
 *  active filters, both results, and whether they agree within the documented tolerance. */
export function ShowCalculation({ calcId, datasetId, filters, extra, compact = false }: {
  calcId: string; datasetId: string | undefined; filters: Filters; extra?: Params; compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={compact ? "btn-ghost btn-sm px-1.5" : "btn-ghost btn-sm"}
              aria-label={`Show calculation for ${calcId.replace(/_/g, " ")}`} title="Show calculation">
        <Code2 className="h-3.5 w-3.5" aria-hidden />{!compact && <span>Show calculation</span>}
      </button>
      {open && <CalcDialog calcId={calcId} datasetId={datasetId} filters={filters} extra={extra} onClose={() => setOpen(false)} />}
    </>
  );
}

function CalcDialog({ calcId, datasetId, filters, extra, onClose }: {
  calcId: string; datasetId: string | undefined; filters: Filters; extra?: Params; onClose: () => void;
}) {
  const [tab, setTab] = useState<"pandas" | "sql" | "results">("pandas");
  const q = useQuery({
    queryKey: ["calc", calcId, datasetId, filters, extra],
    queryFn: () => api<CalculationDetail>(`/calculations/${calcId}`, { params: analysisParams(datasetId, filters, extra) }),
  });
  const d = q.data;
  return (
    <Dialog open onClose={onClose} title={d ? `How "${d.label}" is calculated` : "Calculation"} wide>
      {q.isLoading && <Spinner label="Running pandas and DuckDB" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        <div className="space-y-4">
          <p className="text-sm text-muted">{d.definition}</p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="chip">Dataset {d.dataset_id}</span>
            <span className="chip">n = {d.sample_size.toLocaleString()} restaurants</span>
            {d.filters.length ? d.filters.map((f) => <span key={f} className="chip">{f}</span>) : <span className="chip">No filters</span>}
          </div>
          {!d.available && <Note tone="warning">N/A: {d.reason}</Note>}
          {d.available && (
            <div className={`flex items-start gap-2 rounded-lg p-3 text-sm ${d.match ? "bg-success-soft" : "bg-danger-soft"}`}>
              {d.match ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />}
              <div>
                <p className="font-semibold text-ink">{d.match ? "PASS: pandas and DuckDB agree" : "FAIL: pandas and DuckDB disagree"}</p>
                <p className="text-xs text-muted">Compared with tolerance {d.tolerance}. The SQL below is exactly what was executed.</p>
                {!d.match && <ul className="mt-1 list-disc pl-4 text-xs text-muted">{d.mismatches.slice(0, 5).map((m) => <li key={m}>{m}</li>)}</ul>}
              </div>
            </div>
          )}
          {d.prior?.available && (
            <Note>Bayesian prior for this dataset: C (mean rating) = {d.prior.C?.toFixed(4)}, m = {d.prior.m} ({d.prior.m_source}).</Note>
          )}
          <Segmented label="Calculation view" value={tab} onChange={setTab}
                     options={[{ value: "pandas", label: "Pandas" }, { value: "sql", label: "DuckDB SQL" }, { value: "results", label: "Results" }]} />
          {tab === "pandas" && (
            <div className="space-y-2">
              <pre className="code max-h-80">{d.pandas_code}</pre>
              <details>
                <summary className="cursor-pointer text-xs font-medium text-muted">Filter function applied first (same for every metric)</summary>
                <pre className="code mt-2 max-h-64">{d.filter_code}</pre>
              </details>
            </div>
          )}
          {tab === "sql" && <pre className="code max-h-96">{d.sql}</pre>}
          {tab === "results" && (
            <div className="grid gap-3 md:grid-cols-2">
              <div><p className="label">Pandas result</p><pre className="code max-h-72">{JSON.stringify(d.pandas_result, null, 2)}</pre></div>
              <div><p className="label">DuckDB result</p><pre className="code max-h-72">{JSON.stringify(d.sql_result, null, 2)}</pre></div>
            </div>
          )}
          {d.caveat && <Note>{d.caveat}</Note>}
        </div>
      )}
    </Dialog>
  );
}

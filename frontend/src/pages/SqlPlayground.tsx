import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Loader2, Play, Table2 } from "lucide-react";
import { api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useToast } from "../hooks/useToast";
import { Assumptions, Card, EmptyState, ErrorState, NoDataset, Note, PageHeader, Skeleton } from "../components/ui";

interface SchemaResponse {
  tables: { table: string; rows: number; columns: { name: string; type: string }[] }[];
  examples: { title: string; sql: string }[];
  limits: { timeout_seconds: number; max_rows: number };
}
interface SqlResult { columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean; max_rows: number; elapsed_ms: number }

function toCsv(columns: string[], rows: unknown[][]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
}

export default function SqlPlayground() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const toast = useToast();
  const schema = useQuery({ queryKey: ["sql-schema", ds], queryFn: () => api<SchemaResponse>("/sql/schema", { params: { dataset_id: ds } }), enabled: !!ds });
  const [sql, setSql] = useState("SELECT cuisine, COUNT(*) AS listings\nFROM restaurant_cuisines\nGROUP BY cuisine\nORDER BY listings DESC\nLIMIT 10");
  const run = useMutation({ mutationFn: () => api<SqlResult>("/sql", { method: "POST", body: { sql, dataset_id: ds } }) });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="SQL Playground" description="Query the active dataset with read-only DuckDB SQL." /><NoDataset /></>);

  const exportCsv = () => {
    if (!run.data) return;
    const blob = new Blob([toCsv(run.data.columns, run.data.rows)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `restaurantiq_${ds}_query.csv`; a.click();
    URL.revokeObjectURL(url);
    toast("success", "CSV exported", `${run.data.row_count.toLocaleString()} rows saved.`);
  };

  return (
    <>
      <PageHeader title="SQL Playground" description={`Run read-only SELECT queries with DuckDB against the active dataset (${ds}). Queries time out after ${schema.data?.limits.timeout_seconds ?? 5} seconds and return at most ${(schema.data?.limits.max_rows ?? 1000).toLocaleString()} rows.`} />
      <div className="grid gap-4 xl:grid-cols-[18rem_1fr]">
        <div className="space-y-4">
          <Card title="Schema" subtitle="Tables built from the analysis rows">
            {schema.isLoading && <Skeleton className="h-40" />}
            {schema.isError && <ErrorState error={schema.error} onRetry={() => schema.refetch()} />}
            {schema.data?.tables.map((t) => (
              <details key={t.table} className="mb-2" open={t.table === "restaurants"}>
                <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-ink">
                  <Table2 className="h-3.5 w-3.5 text-subtle" aria-hidden />{t.table}<span className="ml-auto text-xs font-normal tabular-nums text-subtle">{t.rows.toLocaleString()} rows</span>
                </summary>
                <ul className="mt-1 space-y-0.5 pl-6">
                  {t.columns.map((c) => (
                    <li key={c.name} className="flex justify-between gap-2 text-xs">
                      <button className="truncate text-left font-mono text-muted hover:text-accent-ink" onClick={() => setSql((s) => `${s}${s.endsWith(" ") || s.endsWith("\n") ? "" : " "}${c.name}`)} title={`Insert ${c.name}`}>{c.name}</button>
                      <span className="shrink-0 text-subtle">{c.type}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </Card>
          <Card title="Analyst queries" subtitle="Click to load into the editor">
            <ul className="space-y-1">
              {schema.data?.examples.map((e) => (
                <li key={e.title}><button className="w-full rounded-md px-2 py-1.5 text-left text-sm text-muted hover:bg-surface-3 hover:text-ink" onClick={() => setSql(e.sql)}>{e.title}</button></li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          <Card title="Query" actions={<span className="text-xs text-subtle">Ctrl + Enter to run</span>}>
            <label htmlFor="sql-editor" className="sr-only">SQL query</label>
            <textarea id="sql-editor" className="input min-h-[12rem] font-mono text-xs leading-relaxed" spellCheck={false} value={sql}
                      onChange={(e) => setSql(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (!run.isPending) run.mutate(); } }} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn-primary" onClick={() => run.mutate()} disabled={run.isPending || !sql.trim()}>
                {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />} Run query
              </button>
              <button className="btn-secondary" onClick={exportCsv} disabled={!run.data || run.data.row_count === 0}><Download className="h-4 w-4" aria-hidden /> Export CSV</button>
              {run.data && <span className="text-xs text-muted">{run.data.row_count.toLocaleString()} rows · {run.data.elapsed_ms} ms</span>}
            </div>
          </Card>
          {run.isError && <ErrorState error={run.error} />}
          {run.data?.truncated && <Note tone="warning">Results were limited to the first {run.data.max_rows.toLocaleString()} rows. Add a LIMIT or aggregate to see everything.</Note>}
          {run.data && (
            <Card title="Results" bodyClass="p-0">
              {run.data.row_count === 0 ? <EmptyState title="The query returned no rows" /> : (
                <div className="max-h-[32rem] overflow-auto">
                  <table className="table-base">
                    <thead className="sticky top-0"><tr>{run.data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                    <tbody>
                      {run.data.rows.map((r, i) => (
                        <tr key={i}>{r.map((v, j) => (
                          <td key={j} className={typeof v === "number" ? "num" : "max-w-[18rem] truncate"}>
                            {v === null ? <span className="text-subtle">NULL</span> : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString("en-US", { maximumFractionDigits: 4 })) : String(v)}
                          </td>
                        ))}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
      <Assumptions items={[
        "Only single SELECT/WITH statements are accepted; data-changing statements, file access and settings changes are rejected.",
        "DuckDB runs with external (file/network) access disabled and a locked configuration.",
        "Tables contain the analysis rows of the active version: duplicates and invalid rows are already excluded.",
        "rating is normalized to 0-5; NULL means unrated or not provided (never zero).",
        "restaurant_cuisines and restaurant_types are bridge tables (one row per restaurant and value).",
      ]} />
    </>
  );
}

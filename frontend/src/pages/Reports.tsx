import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, Eye, FileArchive, FileSpreadsheet, FileText, Loader2 } from "lucide-react";
import { analysisParams, api, downloadFile } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useFilters } from "../hooks/useFilters";
import { useToast } from "../hooks/useToast";
import { activeFilterCount, filtersToBody, EMPTY_FILTERS } from "../lib/filters";
import { fmtDate, fmtInt } from "../lib/format";
import type { Finding } from "../lib/types";
import { useFilterOptions } from "../components/FilterBar";
import { Assumptions, Card, ErrorState, MultiSelect, NoDataset, Note, PageHeader, SampleBadge, Segmented, Skeleton, Tag } from "../components/ui";

type ReportType = "market_overview" | "cuisine" | "location" | "comparison";
interface ReportData {
  title: string; generated_at: string; report_type: ReportType; length: string;
  dataset: { id: string; name: string; version: number; is_demo: boolean; source_file: string | null };
  scope: { filters: string[]; sample_size: number; total_rows: number };
  reconciliation: Record<string, number>;
  kpis: { label: string; value: string; definition: string }[];
  executive_summary: string[]; findings: Finding[];
  charts: Record<string, { label: string; summary: string }>;
  sections: { heading: string; lines: string[]; table?: string[][] }[];
  opportunities: string[]; limitations: string[]; next_steps: string[];
}

export default function Reports() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const { filters } = useFilters();
  const toast = useToast();
  const opts = useFilterOptions(ds);
  const [scope, setScope] = useState<"full" | "filtered">("full");
  const [type, setType] = useState<ReportType>("market_overview");
  const [length, setLength] = useState<"executive" | "detailed">("executive");
  const [focus, setFocus] = useState("");
  const [cmpKind, setCmpKind] = useState<"cuisine" | "location">("location");
  const [cmpItems, setCmpItems] = useState<string[]>([]);
  const [downloading, setDownloading] = useState<string | null>(null);
  const useFiltered = scope === "filtered";
  const effective = useFiltered ? filters : EMPTY_FILTERS;

  const body = () => ({
    dataset_id: ds, report_type: type, length, use_filters: useFiltered, filters: filtersToBody(effective),
    focus: type === "cuisine" || type === "location" ? focus || null : null,
    compare_kind: type === "comparison" ? cmpKind : null, compare_items: type === "comparison" ? cmpItems : [],
  });
  const preview = useMutation({ mutationFn: () => api<ReportData>("/reports/preview", { method: "POST", body: body() }) });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="Reports" description="Generate PDF reports and BI exports." /><NoDataset /></>);

  const ready = (type !== "cuisine" && type !== "location") || !!focus ? (type !== "comparison" || cmpItems.length >= 2) : false;
  const run = async (key: string, fn: () => Promise<string>) => {
    setDownloading(key);
    try { const name = await fn(); toast("success", "Download ready", name); }
    catch (e) { toast("error", "Download failed", (e as Error).message); }
    finally { setDownloading(null); }
  };
  const pdf = () => run("pdf", () => downloadFile("/reports/pdf", { method: "POST", body: body() }, "report.pdf"));
  const exp = (key: string, path: string) => run(key, () => downloadFile(path, { params: analysisParams(ds, effective) }));
  const focusOptions = type === "cuisine" ? opts.data?.cuisine ?? [] : opts.data?.location ?? [];
  const busy = (k: string) => downloading === k;

  return (
    <>
      <PageHeader title="Reports" description="Generate a PDF report or export data for Power BI / Tableau. Every report is computed on request from the active dataset version, so numbers are never stale." />
      <div className="grid gap-4 xl:grid-cols-[22rem_1fr]">
        <div className="space-y-4">
          <Card title="Report settings">
            <div className="space-y-4">
              <div>
                <p className="label">Scope</p>
                <Segmented label="Scope" value={scope} onChange={setScope} options={[{ value: "full", label: "Full dataset" }, { value: "filtered", label: `Current filters (${activeFilterCount(filters)})` }]} />
                {useFiltered && <p className="mt-1 text-xs text-subtle">{activeFilterCount(filters) ? "Uses the filters set on the Dashboard / Explorer / Market pages." : "No filters are set, so this equals the full dataset."}</p>}
              </div>
              <div>
                <label htmlFor="rtype" className="label">Report type</label>
                <select id="rtype" className="input" value={type} onChange={(e) => { setType(e.target.value as ReportType); setFocus(""); }}>
                  <option value="market_overview">Market overview</option><option value="cuisine">Cuisine</option>
                  <option value="location">Location</option><option value="comparison">Comparison</option>
                </select>
              </div>
              {(type === "cuisine" || type === "location") && (
                <div>
                  <label htmlFor="focus" className="label">{type === "cuisine" ? "Cuisine" : "Location"}</label>
                  <select id="focus" className="input" value={focus} onChange={(e) => setFocus(e.target.value)}>
                    <option value="">Select...</option>
                    {focusOptions.map((o) => <option key={o.value} value={o.value}>{o.value}</option>)}
                  </select>
                </div>
              )}
              {type === "comparison" && (
                <div className="space-y-2">
                  <Segmented label="Compare" value={cmpKind} onChange={(v) => { setCmpKind(v); setCmpItems([]); }} options={[{ value: "location", label: "Locations" }, { value: "cuisine", label: "Cuisines" }]} />
                  <MultiSelect label={`Choose 2-4 ${cmpKind === "cuisine" ? "cuisines" : "locations"}`} options={(cmpKind === "cuisine" ? opts.data?.cuisine : opts.data?.location) ?? []}
                               value={cmpItems} onChange={(v) => setCmpItems(v.slice(0, 4))} />
                </div>
              )}
              <div>
                <p className="label">Length</p>
                <Segmented label="Length" value={length} onChange={setLength} options={[{ value: "executive", label: "Executive" }, { value: "detailed", label: "Detailed" }]} />
              </div>
              <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                <button className="btn-secondary" onClick={() => preview.mutate()} disabled={!ready || preview.isPending}>
                  {preview.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />} Preview
                </button>
                <button className="btn-primary" onClick={pdf} disabled={!ready || downloading !== null}>
                  {busy("pdf") ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileText className="h-4 w-4" aria-hidden />} Download PDF
                </button>
              </div>
              {!ready && <p className="text-xs text-subtle">{type === "comparison" ? "Choose at least two items." : `Choose a ${type}.`}</p>}
            </div>
          </Card>
          <Card title="Data exports" subtitle={`Scope: ${useFiltered && activeFilterCount(filters) ? "current filters" : "full dataset"} · version ${ds}`}>
            <div className="space-y-2">
              <ExportButton busy={busy("filtered")} disabled={downloading !== null} icon={<FileSpreadsheet className="h-4 w-4" aria-hidden />} label="Filtered CSV" hint="Analysis rows with every source column" onClick={() => exp("filtered", "/export/filtered.csv")} />
              <ExportButton busy={busy("flat")} disabled={downloading !== null} icon={<FileSpreadsheet className="h-4 w-4" aria-hidden />} label="BI-ready flat CSV" hint="Tidy one-row-per-restaurant table" onClick={() => exp("flat", "/export/bi-flat.csv")} />
              <ExportButton busy={busy("star")} disabled={downloading !== null} icon={<FileArchive className="h-4 w-4" aria-hidden />} label="Star schema (ZIP)" hint="fact + dim_location + dim_cuisine + bridge + README" onClick={() => exp("star", "/export/star-schema.zip")} />
              <ExportButton busy={busy("cleaned")} disabled={downloading !== null} icon={<Download className="h-4 w-4" aria-hidden />} label="Full cleaned dataset" hint="All de-duplicated rows with quality flags (ignores filters)" onClick={() => run("cleaned", () => downloadFile(`/datasets/${ds}/cleaned.csv`))} />
            </div>
          </Card>
        </div>

        <div className="min-w-0">
          {preview.isError && <ErrorState error={preview.error} />}
          {!preview.data && !preview.isPending && <Card><p className="py-8 text-center text-sm text-muted">Choose settings and select Preview to see the report here. The PDF contains the same computed content plus charts.</p></Card>}
          {preview.isPending && <Skeleton className="h-96" />}
          {preview.data && <ReportPreview r={preview.data} />}
        </div>
      </div>
      <Assumptions items={[
        "Reports and exports are recomputed on every request from the selected dataset version and scope.",
        "Each report lists its generation time, dataset version, filters, reconciliation and limitations.",
        "Opportunities are exploratory suggestions to investigate, not predictions.",
        "Costs in the PDF are written with currency codes (for example INR 450).",
      ]} />
    </>
  );
}

function ExportButton({ label, hint, icon, onClick, busy, disabled }: { label: string; hint: string; icon: React.ReactNode; onClick: () => void; busy: boolean; disabled: boolean }) {
  return (
    <button className="flex w-full items-center gap-3 rounded-lg border border-line p-3 text-left transition hover:bg-surface-2 disabled:opacity-60" onClick={onClick} disabled={disabled}>
      <span className="text-subtle">{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}</span>
      <span className="min-w-0"><span className="block text-sm font-medium text-ink">{label}</span><span className="block text-xs text-subtle">{hint}</span></span>
    </button>
  );
}

function ReportPreview({ r }: { r: ReportData }) {
  return (
    <article className="card space-y-6 p-6">
      <header>
        <h2 className="text-xl font-semibold text-ink">{r.title}</h2>
        <p className="mt-1 text-xs text-muted">Generated {fmtDate(r.generated_at)} · {r.dataset.name} ({r.dataset.id}) · {r.length} report</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">{r.dataset.is_demo && <SampleBadge />}
          {r.scope.filters.map((f) => <span key={f} className="chip">{f}</span>)}<span className="chip">{fmtInt(r.scope.sample_size)} of {fmtInt(r.scope.total_rows)} restaurants</span></div>
      </header>
      <PreviewSection title="Executive summary"><ul className="list-disc space-y-1 pl-5 text-sm text-ink">{r.executive_summary.map((s) => <li key={s}>{s}</li>)}</ul></PreviewSection>
      <PreviewSection title="Dataset and reconciliation">
        <p className="text-sm text-muted">Raw {fmtInt(r.reconciliation.raw_rows)} → duplicates removed {fmtInt(r.reconciliation.duplicates_removed)} → invalid excluded {fmtInt(r.reconciliation.invalid_rows_excluded)} → rows used {fmtInt(r.reconciliation.rows_used_in_analysis)} (unrated kept: {fmtInt(r.reconciliation.unrated_rows_in_analysis)}).</p>
      </PreviewSection>
      <PreviewSection title="KPIs">
        <div className="grid gap-2 sm:grid-cols-3">{r.kpis.map((k) => (
          <div key={k.label} className="rounded-lg bg-surface-2 p-3"><p className="text-xs text-muted">{k.label}</p><p className="text-lg font-semibold tabular-nums text-ink">{k.value}</p></div>
        ))}</div>
      </PreviewSection>
      {r.findings.length > 0 && <PreviewSection title="Findings"><ul className="space-y-2">{r.findings.map((f) => <li key={f.title} className="flex gap-2 text-sm"><Tag kind={f.tag} /><span><b className="text-ink">{f.title}.</b> <span className="text-muted">{f.detail}</span></span></li>)}</ul></PreviewSection>}
      {Object.keys(r.charts).length > 0 && <PreviewSection title="Chart summaries"><ul className="space-y-1 text-sm">{Object.values(r.charts).map((c) => <li key={c.label}><b className="text-ink">{c.label}:</b> <span className="text-muted">{c.summary}</span></li>)}</ul><p className="mt-1 text-xs text-subtle">Charts are drawn in the PDF.</p></PreviewSection>}
      {r.sections.map((s) => (
        <PreviewSection key={s.heading} title={s.heading}>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink">{s.lines.map((l) => <li key={l}>{l}</li>)}</ul>
          {s.table && (
            <div className="mt-2 overflow-x-auto"><table className="table-base text-xs"><thead><tr>{s.table[0].map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>{s.table.slice(1).map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j} className={j ? "num" : ""}>{c}</td>)}</tr>)}</tbody></table></div>
          )}
        </PreviewSection>
      ))}
      <PreviewSection title="Opportunities to investigate (exploratory)"><ul className="list-disc space-y-1 pl-5 text-sm text-ink">{r.opportunities.map((o) => <li key={o}>{o}</li>)}</ul></PreviewSection>
      <PreviewSection title="Limitations"><ul className="list-disc space-y-1 pl-5 text-sm text-muted">{r.limitations.map((o) => <li key={o}>{o}</li>)}</ul></PreviewSection>
      <PreviewSection title="Next steps"><ul className="list-disc space-y-1 pl-5 text-sm text-muted">{r.next_steps.map((o) => <li key={o}>{o}</li>)}</ul></PreviewSection>
      <Note>This preview and the PDF are generated from the same computation.</Note>
    </article>
  );
}

function PreviewSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-subtle">{title}</h3>{children}</section>;
}

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { analysisParams, api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useFilters } from "../hooks/useFilters";
import type { DashboardData, Result, Row } from "../lib/types";
import { fmtInt, fmtMoney, fmtNum, fmtRating } from "../lib/format";
import { FilterBar } from "../components/FilterBar";
import { KpiCard } from "../components/KpiCard";
import { ShowCalculation } from "../components/ShowCalculation";
import { FindingsPanel } from "../components/Findings";
import { Donut, HBarChart, ScatterPlot, VBarChart, useChartColors } from "../components/charts";
import { Assumptions, Card, EmptyState, ErrorState, NoDataset, Note, PageHeader, SampleBadge, SectionTitle, Skeleton, Unavailable } from "../components/ui";
import type { Filters } from "../lib/filters";
import type { ReactNode } from "react";

export function ContextLine({ ctx }: { ctx: DashboardData["context"] }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span>Dataset <span className="font-semibold text-ink">{ctx.dataset_name}</span> ({ctx.dataset_id})</span>
      <span aria-hidden>·</span>
      <span><span className="font-semibold tabular-nums text-ink">{ctx.sample_size.toLocaleString()}</span> of {ctx.total_rows.toLocaleString()} restaurants in view</span>
      <span aria-hidden>·</span>
      <span>{ctx.filters.length ? ctx.filters.join(" | ") : "No filters applied"}</span>
      {ctx.is_demo && <SampleBadge />}
    </div>
  );
}

function ChartCard({ id, result, title, subtitle, datasetId, filters, children, className }: {
  id: string; result: Result<unknown> | undefined; title: string; subtitle?: ReactNode; datasetId?: string; filters: Filters;
  children: (data: never) => ReactNode; className?: string;
}) {
  const empty = result?.available && Array.isArray(result.data) && result.data.length === 0;
  return (
    <Card title={title} subtitle={subtitle} className={className}
          actions={<ShowCalculation calcId={id} datasetId={datasetId} filters={filters} />}>
      {!result ? <Skeleton className="h-56" /> :
        !result.available ? <Unavailable reason={result.reason} /> :
          empty ? <EmptyState title="No data for this selection" message="Try removing a filter." /> :
            children(result.data as never)}
      {result?.caveat && result.available && <p className="mt-3 text-xs text-subtle">{result.caveat}</p>}
    </Card>
  );
}

export default function Dashboard() {
  const active = useActiveDataset();
  const { filters, reset } = useFilters();
  const ds = active.data?.dataset_id;
  const q = useQuery({
    queryKey: ["dashboard", ds, filters],
    queryFn: () => api<DashboardData>("/dashboard", { params: analysisParams(ds, filters) }),
    enabled: !!ds,
    placeholderData: keepPreviousData,
  });
  const colors = useChartColors();

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="Dashboard" description="KPIs, distributions and key findings for the active dataset." /><NoDataset /></>);

  const d = q.data;
  const c = d?.charts;
  const minN = d?.context.settings.min_group_n ?? 10;
  const costCur = d?.cost_unit ?? null;
  const noRows = d && d.context.sample_size === 0;

  return (
    <>
      <PageHeader title="Dashboard" description="KPIs, distributions and key findings for the active dataset. Every number is computed by the backend from the current filters." />
      <FilterBar datasetId={ds} />
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && <ContextLine ctx={d.context} />}
      {noRows && (
        <div className="card mb-6"><EmptyState title="No restaurants match these filters" message="Remove a filter or reset all filters to see results."
                                               action={<button className="btn-secondary" onClick={reset}>Reset filters</button>} /></div>
      )}

      <SectionTitle hint={q.isFetching ? "Updating..." : undefined}>Descriptive statistics</SectionTitle>
      <div className={`grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 ${q.isFetching ? "opacity-70 transition-opacity" : ""}`}>
        {d ? d.kpis.map((k) => <KpiCard key={k.id} kpi={k} datasetId={ds} filters={filters} />)
          : Array.from({ length: 9 }).map((_, i) => <Skeleton key={i} className="h-[8.5rem]" />)}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard id="top_cuisines" result={c?.top_cuisines} title="Top cuisines by number of listings" subtitle="Top 15; each restaurant counted once per cuisine" datasetId={ds} filters={filters}>
          {(data: Row[]) => <HBarChart data={data} labelKey="label" valueKey="value" format={(v) => fmtInt(v)}
                                         tooltip={(r) => ({ title: String(r.label), rows: [{ label: "Listings", value: fmtInt(r.value) }] })} />}
        </ChartCard>
        <ChartCard id="by_location" result={c?.by_location} title="Restaurants by location" subtitle="Top 15 locations by listing count" datasetId={ds} filters={filters}>
          {(data: Row[]) => <HBarChart data={data} labelKey="label" valueKey="value" format={(v) => fmtInt(v)}
                                         tooltip={(r) => ({ title: String(r.label), rows: [{ label: "Listings", value: fmtInt(r.value) }] })} />}
        </ChartCard>
        <ChartCard id="rating_distribution" result={c?.rating_distribution} title="Rating distribution" subtitle="Rated restaurants per 0.2-point band (0–5 scale)" datasetId={ds} filters={filters}>
          {(data: Row[]) => <VBarChart data={data} labelKey="label" valueKey="value"
                                         tooltip={(r) => ({ title: `Rating ${String(r.label)}`, rows: [{ label: "Restaurants", value: fmtInt(r.value) }] })} />}
        </ChartCard>
        <ChartCard id="price_tiers" result={c?.price_tiers} title="Price tier mix" subtitle="Dataset-relative cost terciles" datasetId={ds} filters={filters}>
          {(data: { label: string; value: number }[]) => {
            const total = data.reduce((a, b) => a + b.value, 0);
            return <Donut data={data} total={total} centerLabel="with cost" />;
          }}
        </ChartCard>
      </div>

      <SectionTitle>Deeper view</SectionTitle>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard id="wr_by_cuisine" result={c?.wr_by_cuisine} title="Weighted rating by cuisine"
                   subtitle={`Top 15 by weighted rating; gray bars have fewer than ${minN} rated restaurants (insufficient sample)`} datasetId={ds} filters={filters}>
          {(data: Row[]) => {
            const rows = data.slice(0, 15);
            return (
              <>
                <HBarChart data={rows} labelKey="cuisine" valueKey="weighted_rating" format={(v) => fmtRating(v)}
                           colorFor={(r) => (r.sufficient_sample ? colors.series[0] : colors.muted)}
                           tooltip={(r) => ({ title: `${String(r.cuisine)}${r.sufficient_sample ? "" : " (insufficient sample)"}`,
                             rows: [{ label: "Weighted rating", value: fmtNum(r.weighted_rating, 3) }, { label: "Raw mean rating", value: fmtNum(r.mean_rating, 3) },
                                    { label: "Rated restaurants", value: fmtInt(r.n_rated) }, { label: "Listings", value: fmtInt(r.listings) }] })} />
                <p className="mt-2 text-xs text-subtle">Only cuisines with at least {minN} rated restaurants are ranked first; smaller groups are shown for context, not as winners.</p>
              </>
            );
          }}
        </ChartCard>
        <ChartCard id="median_cost_by_location" result={c?.median_cost_by_location} title="Median cost by location"
                   subtitle={`Top 15 by median cost${costCur ? ` (${costCur})` : ""}; gray bars have fewer than ${minN} priced listings`} datasetId={ds} filters={filters}>
          {(data: Row[]) => <HBarChart data={data.slice(0, 15)} labelKey="location" valueKey="median_cost" format={(v) => fmtMoney(v, costCur)}
                                         colorFor={(r) => (r.sufficient_sample ? colors.series[0] : colors.muted)}
                                         tooltip={(r) => ({ title: String(r.location), rows: [{ label: "Median cost", value: fmtMoney(r.median_cost, costCur) },
                                           { label: "Mean cost", value: fmtMoney(r.mean_cost, costCur) }, { label: "Priced listings", value: fmtInt(r.n_cost) }] })} />}
        </ChartCard>
        <ChartCard id="rating_vs_votes" result={c?.rating_vs_votes} title="Rating vs votes" subtitle="Votes on a log scale (votes + 1); each point is one rated restaurant" datasetId={ds} filters={filters}>
          {(data: { total_points: number; shown_points: number; points: Row[] }) => (
            <>
              <ScatterPlot points={data.points} xKey="review_count" yKey="rating" xLabel="Votes (log scale)" yLabel="Rating" logX nameKey="restaurant_name" />
              <p className="mt-2 text-xs text-subtle">Showing {data.shown_points.toLocaleString()} of {data.total_points.toLocaleString()} points
                {data.shown_points < data.total_points ? " (deterministic sample)" : ""}. Correlation is not causation; see Market Analysis for the Spearman test.</p>
            </>
          )}
        </ChartCard>
        <ChartCard id="distribution_profile" result={c?.distribution_profile} title="Distribution profile" subtitle="Median sits beside mean because votes and cost are usually right-skewed" datasetId={ds} filters={filters}>
          {(data: Row[]) => (
            <div className="-mx-4 overflow-x-auto">
              <table className="table-base">
                <thead><tr><th>Metric</th><th className="num">n</th><th className="num">Mean</th><th className="num">Median</th><th className="num">IQR</th><th className="num">P10</th><th className="num">P90</th><th className="num">Skew</th></tr></thead>
                <tbody>
                  {data.map((r) => {
                    const f = r.metric === "cost" ? (v: unknown) => fmtMoney(v, costCur) : r.metric === "rating" ? (v: unknown) => fmtNum(v, 2) : (v: unknown) => fmtNum(v, 0);
                    return (
                      <tr key={String(r.metric)}>
                        <td className="font-medium">{String(r.label)}</td><td className="num">{fmtInt(r.n)}</td><td className="num">{f(r.mean)}</td>
                        <td className="num">{f(r.median)}</td><td className="num">{f(r.iqr)}</td><td className="num">{f(r.p10)}</td><td className="num">{f(r.p90)}</td>
                        <td className="num">{fmtNum(r.skewness, 2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-3 px-4 text-xs text-subtle">Skew above 1 means a long right tail: a few very large values pull the mean above the median.</p>
            </div>
          )}
        </ChartCard>
      </div>

      {d?.outlier_impact && (
        <div className="mt-4">
          <Card title="Cost outlier impact" subtitle={`${d.outlier_impact.outliers.toLocaleString()} cost outliers flagged by the 1.5 × IQR rule (kept, not deleted)`}>
            <div className="-mx-4 overflow-x-auto">
              <table className="table-base">
                <thead><tr><th>Statistic</th><th className="num">With outliers</th><th className="num">Without outliers</th></tr></thead>
                <tbody>
                  {(["n", "mean", "median", "std"] as const).map((k) => (
                    <tr key={k}><td className="font-medium">{k === "n" ? "Priced restaurants" : k === "std" ? "Standard deviation" : k[0].toUpperCase() + k.slice(1)}</td>
                      <td className="num">{k === "n" ? fmtInt(d.outlier_impact!.with_outliers.n) : fmtMoney(d.outlier_impact!.with_outliers[k], costCur)}</td>
                      <td className="num">{k === "n" ? fmtInt(d.outlier_impact!.without_outliers.n) : fmtMoney(d.outlier_impact!.without_outliers[k], costCur)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-subtle">The median barely moves while the mean and spread change: that is why medians are reported beside means.</p>
          </Card>
        </div>
      )}

      <SectionTitle>Statistical tests and recommendations to investigate</SectionTitle>
      {d ? <FindingsPanel findings={d.findings} /> : <Skeleton className="h-48" />}
      <div className="mt-3"><Note>Statistical tests (Spearman, Mann-Whitney) and the Opportunity Score are on the Market Analysis page, with sample sizes and caveats.</Note></div>

      <Assumptions items={[
        "Ratings are snapshot, user-generated scores from the source platform; they are not revenue, demand, footfall or profit.",
        "Unrated restaurants are excluded from rating statistics but kept for counts, costs and locations.",
        "Invalid rows (rating outside the scale, negative votes or cost) are excluded from all analysis and listed on the Data page.",
        "Weighted rating = v/(v+m)·R + m/(v+m)·C; it shrinks ratings with few votes toward the dataset mean.",
        "Costs are listed prices (often approximate, e.g. 'for two'); mixed currencies are never combined.",
        `Group rankings require at least ${minN} restaurants by default (change in Settings).`,
      ]} />
    </>
  );
}

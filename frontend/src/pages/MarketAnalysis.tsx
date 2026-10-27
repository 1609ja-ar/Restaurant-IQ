import { useState, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { analysisParams, api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useDebounced, useFilters } from "../hooks/useFilters";
import { fmtFraction, fmtInt, fmtMoney, fmtNum, fmtP, fmtPct, fmtRating } from "../lib/format";
import type { AnalysisContext, Capabilities, Result, Row } from "../lib/types";
import { FilterBar, useFilterOptions } from "../components/FilterBar";
import { ShowCalculation } from "../components/ShowCalculation";
import { HBarChart, useChartColors } from "../components/charts";
import { ContextLine } from "./Dashboard";
import { Assumptions, Card, EmptyState, ErrorState, NoDataset, Note, PageHeader, SectionTitle, Skeleton, Tag, Unavailable } from "../components/ui";

interface Weights { rating: number; engagement: number; low_saturation: number }
interface MarketData {
  context: AnalysisContext;
  capabilities: Capabilities;
  cuisine_popularity: Result<Row[]>;
  location_density: Result<Row[]>;
  price_tier_analysis: Result<Row[]>;
  market_gaps: Result<{ benchmark_weighted_rating: number | null; median_listings: number | null; rows: Row[] }>;
  types_by_tier: Result<Row[]>;
  spearman: Result<Row[]>;
  mann_whitney: Result<Row[]>;
  opportunity: Result<Row[]> & { weights: Weights; min_n: number };
  heatmap: Result<{ locations: string[]; cuisines: string[]; cells: Row[] }>;
  sensitivity: { scenario: string; weights: Weights; top: { location: string; cuisine: string; score: number }[] }[] | null;
  focus_cuisine: { cuisine: string; min_location_listings: number; rows: Row[] } | null;
}

function Section<T>({ result, children }: { result: Result<T> | undefined; children: (d: T) => ReactNode }) {
  if (!result) return <Skeleton className="h-48" />;
  if (!result.available) return <Unavailable reason={result.reason} />;
  if (Array.isArray(result.data) && result.data.length === 0) return <EmptyState title="No data for this selection" message="Try removing a filter." />;
  return <>{children(result.data as T)}</>;
}

function Insufficient({ ok }: { ok: unknown }) {
  return ok ? null : <span className="ml-1 rounded bg-surface-3 px-1 text-2xs font-medium text-subtle" title="Below the minimum sample size">small n</span>;
}

export default function MarketAnalysis() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const { filters } = useFilters();
  const opts = useFilterOptions(ds);
  const [weights, setWeights] = useState<Weights>({ rating: 40, engagement: 30, low_saturation: 30 });
  const w = useDebounced(weights, 250);
  const [focus, setFocus] = useState("");
  const weightParams = { w_rating: w.rating, w_engagement: w.engagement, w_low_saturation: w.low_saturation };

  const q = useQuery({
    queryKey: ["market", ds, filters, w, focus],
    queryFn: () => api<MarketData>("/market", { params: analysisParams(ds, filters, { ...weightParams, focus_cuisine: focus || undefined }) }),
    enabled: !!ds,
    placeholderData: keepPreviousData,
  });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="Market Analysis" description="Cuisine popularity, listing density, price tiers and statistical tests." /><NoDataset /></>);
  const d = q.data;
  const minN = d?.context.settings.min_group_n ?? 10;
  const cur = active.data.currencies.length === 1 ? active.data.currencies[0] : filters.currency;
  const calc = (id: string, extra?: Record<string, number>) => <ShowCalculation calcId={id} datasetId={ds} filters={filters} extra={extra} />;

  return (
    <>
      <PageHeader title="Market Analysis" description="Where listings concentrate, how cost and ratings vary, which differences are statistically supported, and which segments may be worth investigating." />
      <FilterBar datasetId={ds} />
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {d && <ContextLine ctx={d.context} />}

      <SectionTitle hint={q.isFetching ? "Updating..." : undefined}>Descriptive statistics</SectionTitle>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Cuisine popularity" subtitle="Listings and share of the selection; a restaurant counts once per cuisine" actions={calc("cuisine_popularity")}>
          <Section result={d?.cuisine_popularity}>{(rows) => <PopularityTable rows={rows} minN={minN} />}</Section>
        </Card>
        <Card title="Location listing density" subtitle="Number of listings per location (supply of listings, not demand)" actions={calc("location_density")}>
          <Section result={d?.location_density}>{(rows) => (
            <HBarChart data={rows.slice(0, 15)} labelKey="location" valueKey="listings" format={(v) => fmtInt(v)}
                       tooltip={(r) => ({ title: String(r.location), rows: [{ label: "Listings", value: fmtInt(r.listings) }, { label: "Share", value: fmtPct(r.share_pct) },
                         { label: "Mean rating", value: fmtRating(r.mean_rating) }, { label: "Distinct cuisines", value: fmtInt(r.distinct_cuisines) },
                         { label: "Median cost", value: fmtMoney(r.median_cost, cur) }] })} />
          )}</Section>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Card title="Price tier analysis" subtitle="How cost and rating vary across dataset-relative cost terciles" actions={calc("price_tier_analysis")} bodyClass="p-0">
          <div className="p-4 pt-0"><Section result={d?.price_tier_analysis}>{(rows) => (
            <div className="-mx-4 overflow-x-auto">
              <table className="table-base">
                <thead><tr><th>Tier</th><th className="num">Listings</th><th className="num">Cost range</th><th className="num">Median cost</th><th className="num">Mean rating</th><th className="num">Median rating</th><th className="num">Weighted</th><th className="num">Median votes</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={String(r.price_tier)}><td className="font-medium">{String(r.price_tier)}<Insufficient ok={r.sufficient_sample} /></td><td className="num">{fmtInt(r.listings)}</td>
                    <td className="num">{fmtMoney(r.min_cost, cur)}–{fmtMoney(r.max_cost, cur)}</td><td className="num">{fmtMoney(r.median_cost, cur)}</td>
                    <td className="num">{fmtRating(r.mean_rating)}</td><td className="num">{fmtRating(r.median_rating)}</td><td className="num">{fmtRating(r.weighted_rating)}</td><td className="num">{fmtInt(r.median_votes)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}</Section></div>
        </Card>
        <Card title="Fewer listings for a selected cuisine" subtitle={`Locations with at least ${minN} listings, sorted by the cuisine's share (lowest first)`}>
          <label htmlFor="focus" className="label">Cuisine</label>
          <select id="focus" className="input mb-3" value={focus} onChange={(e) => setFocus(e.target.value)} disabled={!opts.data?.cuisine.length}>
            <option value="">Select a cuisine</option>
            {opts.data?.cuisine.map((c) => <option key={c.value} value={c.value}>{c.value}</option>)}
          </select>
          {!focus && <p className="text-sm text-muted">Pick a cuisine to see where it is least represented among listings.</p>}
          {focus && d?.focus_cuisine && (d.focus_cuisine.rows.length === 0 ? <EmptyState title="No location has enough listings" /> : (
            <div className="-mx-4 max-h-72 overflow-auto">
              <table className="table-base">
                <thead className="sticky top-0"><tr><th>Location</th><th className="num">{focus} listings</th><th className="num">All listings</th><th className="num">Share</th></tr></thead>
                <tbody>{d.focus_cuisine.rows.map((r) => (
                  <tr key={String(r.location)}><td>{String(r.location)}</td><td className="num">{fmtInt(r.listings)}</td><td className="num">{fmtInt(r.location_listings)}</td><td className="num">{fmtFraction(r.share_in_location)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ))}
          {focus && <p className="mt-3 text-xs text-subtle">Few listings can mean an unmet niche or simply low demand; listings alone cannot tell which.</p>}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Cuisine by location heatmap" subtitle="Top 10 locations × top 10 cuisines. Cell = listings; shading = location quotient (LQ); LQ above 1 means over-represented, below 1 under-represented"
              actions={calc("saturation")}>
          <Section result={d?.heatmap}>{(hm) => <Heatmap hm={hm} />}</Section>
        </Card>
      </div>

      <SectionTitle>Statistical tests and correlations</SectionTitle>
      <StatTests d={d} calc={calc} />

      <SectionTitle>Recommendations to investigate</SectionTitle>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="High-rating, low-listing cuisines" subtitle={`Weighted rating above the selection average and fewer listings than the median cuisine; n ≥ ${minN}`} actions={calc("market_gaps")}>
          <Section result={d?.market_gaps}>{(g) => g.rows.length === 0 ? (
            <EmptyState title="No cuisine meets all three conditions" message="This is a valid result: no under-listed cuisine stands out with enough rated restaurants." />
          ) : (
            <>
              <p className="mb-2 text-xs text-muted">Benchmark weighted rating {fmtNum(g.benchmark_weighted_rating, 3)}; median listings per cuisine {fmtInt(g.median_listings)}.</p>
              <ul className="divide-y divide-line">
                {g.rows.map((r) => (
                  <li key={String(r.cuisine)} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span className="flex items-center gap-2"><Tag kind="Suggestion" /><span className="font-medium text-ink">{String(r.cuisine)}</span></span>
                    <span className="text-right tabular-nums text-muted">WR {fmtNum(r.weighted_rating, 3)} · {fmtInt(r.listings)} listings · n={fmtInt(r.n_rated)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}</Section>
        </Card>
        <Card title="Best restaurant types within each price tier" subtitle={`Highest weighted rating per tier among types with n ≥ ${minN}`} actions={calc("types_by_tier")}>
          <Section result={d?.types_by_tier}>{(rows) => <TypesByTier rows={rows} />}</Section>
        </Card>
      </div>

      <div className="mt-4">
        <Opportunity d={d} weights={weights} setWeights={setWeights} calc={calc("opportunity", weightParams)} />
      </div>

      <Assumptions items={[
        "All results describe restaurant listings from one snapshot. They do not measure demand, footfall, revenue or profitability.",
        "Ratings are platform scores and can be biased (who reviews, platform algorithms, fake reviews).",
        `Groups with fewer than ${minN} rated restaurants are flagged and never presented as reliable winners.`,
        "Spearman correlations measure monotonic association only; correlation is not causation.",
        "Mann-Whitney tests compare rating distributions between Yes and No groups; unknown values are excluded. Differences may be driven by restaurant type, price or location (confounding).",
        "The Opportunity Score is an exploratory, weight-dependent ranking. Check the sensitivity view: results that change with the weights are not robust.",
        "Location quotient and listing density reflect how many listings exist, not how many customers there are.",
      ]} />
    </>
  );
}

function PopularityTable({ rows, minN }: { rows: Row[]; minN: number }) {
  return (
    <div className="-mx-4 max-h-[22rem] overflow-auto">
      <table className="table-base">
        <thead className="sticky top-0"><tr><th>Cuisine</th><th className="num">Listings</th><th className="num">Share</th><th className="num">Rated</th><th className="num">Mean rating</th><th className="num">Weighted</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={String(r.cuisine)}><td className="font-medium">{String(r.cuisine)}<Insufficient ok={r.sufficient_sample} /></td><td className="num">{fmtInt(r.listings)}</td>
            <td className="num">{fmtPct(r.share_pct)}</td><td className="num">{fmtInt(r.n_rated)}</td><td className="num">{fmtRating(r.mean_rating)}</td><td className="num">{fmtRating(r.weighted_rating)}</td></tr>
        ))}</tbody>
      </table>
      <p className="mt-2 px-4 text-xs text-subtle">"small n" = fewer than {minN} rated restaurants. Shares add up to more than 100% because restaurants list several cuisines.</p>
    </div>
  );
}

function Heatmap({ hm }: { hm: { locations: string[]; cuisines: string[]; cells: Row[] } }) {
  const c = useChartColors();
  const map = new Map(hm.cells.map((r) => [`${r.location}|${r.cuisine}`, r]));
  const shade = (lq: number | undefined) => {
    if (lq === undefined) return "transparent";
    const t = Math.max(0, Math.min(1, Math.log2(lq + 1e-9) / 2 + 0.5)); // LQ 0.5 -> 0.25, 1 -> 0.5, 2 -> 0.75
    return `color-mix(in srgb, ${c.series[0]} ${Math.round(8 + t * 50)}%, transparent)`;
  };
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="table-base text-xs">
        <thead><tr><th className="sticky left-0 z-10 bg-surface-2">Location</th>{hm.cuisines.map((cu) => <th key={cu} className="num normal-case">{cu}</th>)}</tr></thead>
        <tbody>{hm.locations.map((loc) => (
          <tr key={loc}><td className="sticky left-0 z-10 whitespace-nowrap bg-surface font-medium">{loc}</td>
            {hm.cuisines.map((cu) => {
              const cell = map.get(`${loc}|${cu}`);
              const lq = cell ? Number(cell.location_quotient) : undefined;
              return (
                <td key={cu} className="num" style={{ background: shade(lq) }}
                    title={cell ? `${cu} in ${loc}: ${cell.listings} listings, ${fmtFraction(cell.share_in_location)} of the location, LQ ${fmtNum(lq, 2)}` : `${cu} in ${loc}: 0 listings`}>
                  {cell ? fmtInt(cell.listings) : <span className="text-subtle">0</span>}
                </td>
              );
            })}</tr>
        ))}</tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-3 px-4 text-xs text-muted">
        <span>Shading:</span>
        {[0.5, 1, 2].map((v) => <span key={v} className="flex items-center gap-1"><span className="h-3 w-5 rounded-sm border border-line" style={{ background: shade(v) }} />LQ {v}</span>)}
        <span>Hover a cell for exact values.</span>
      </div>
    </div>
  );
}

function StatTests({ d, calc }: { d: MarketData | undefined; calc: (id: string) => ReactNode }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Spearman rank correlations" subtitle="Monotonic association between numeric fields (rows with both values)" actions={calc("spearman")}>
        <Section result={d?.spearman}>{(rows) => (
          <div className="space-y-3">
            {rows.map((r) => (
              <div key={`${r.x}-${r.y}`} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="flex items-center gap-2"><Tag kind="Statistical" /><span className="text-sm font-semibold text-ink">{String(r.label)}</span></span>
                  <span className="text-sm tabular-nums text-muted">rho = <span className="font-semibold text-ink">{fmtNum(r.rho, 3)}</span> · p = {fmtP(r.p_value)} · n = {fmtInt(r.n)}</span>
                </div>
                <p className="mt-1 text-xs text-muted">{String(r.note ?? "")}</p>
              </div>
            ))}
          </div>
        )}</Section>
      </Card>
      <Card title="Mann-Whitney U tests" subtitle="Do ratings differ between Yes and No groups? Unknown values are excluded" actions={calc("mann_whitney")}>
        <Section result={d?.mann_whitney}>{(rows) => rows.length === 0 ? <Unavailable reason="Requires an online-order or table-booking Yes/No column." /> : (
          <div className="space-y-3">
            {rows.map((r) => (
              <div key={String(r.group_field)} className="rounded-lg border border-line p-3">
                <div className="flex items-center gap-2"><Tag kind="Statistical" /><span className="text-sm font-semibold text-ink">{String(r.label)}</span></div>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                  <div><dt className="text-subtle">n (Yes / No)</dt><dd className="tabular-nums text-ink">{fmtInt(r.n_yes)} / {fmtInt(r.n_no)}</dd></div>
                  <div><dt className="text-subtle">Median (Yes / No)</dt><dd className="tabular-nums text-ink">{fmtNum(r.median_yes, 2)} / {fmtNum(r.median_no, 2)}</dd></div>
                  <div><dt className="text-subtle">p-value</dt><dd className="tabular-nums text-ink">{fmtP(r.p_value)}</dd></div>
                  <div><dt className="text-subtle">Effect size r</dt><dd className="tabular-nums text-ink">{fmtNum(r.effect_size_r, 3)}</dd></div>
                </dl>
                <p className="mt-2 text-xs text-muted">{String(r.note ?? "")}</p>
              </div>
            ))}
          </div>
        )}</Section>
      </Card>
    </div>
  );
}

function TypesByTier({ rows }: { rows: Row[] }) {
  const tiers = Array.from(new Set(rows.map((r) => String(r.price_tier))));
  return (
    <div className="space-y-3">
      {tiers.map((t) => {
        const inTier = rows.filter((r) => r.price_tier === t);
        const ranked = inTier.filter((r) => r.sufficient_sample).slice(0, 3);
        return (
          <div key={t}>
            <p className="text-xs font-semibold uppercase tracking-wide text-subtle">{t}</p>
            {ranked.length === 0 ? <p className="text-sm text-muted">No type has enough rated restaurants in this tier.</p> : (
              <ol className="mt-1 space-y-1">{ranked.map((r, i) => (
                <li key={String(r.restaurant_type)} className="flex justify-between gap-3 text-sm">
                  <span className="text-ink">{i + 1}. {String(r.restaurant_type)}</span>
                  <span className="tabular-nums text-muted">WR {fmtNum(r.weighted_rating, 3)} · n={fmtInt(r.n_rated)}</span>
                </li>))}</ol>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Opportunity({ d, weights, setWeights, calc }: { d: MarketData | undefined; weights: Weights; setWeights: (w: Weights) => void; calc: ReactNode }) {
  const total = weights.rating + weights.engagement + weights.low_saturation;
  const pct = (v: number) => (total ? `${Math.round((v / total) * 100)}%` : "0%");
  const slider = (key: keyof Weights, label: string, help: string) => (
    <div>
      <div className="flex justify-between text-sm"><label htmlFor={`w-${key}`} className="font-medium text-ink">{label}</label><span className="tabular-nums text-muted">{pct(weights[key])}</span></div>
      <input id={`w-${key}`} type="range" min={0} max={100} step={5} value={weights[key]} onChange={(e) => setWeights({ ...weights, [key]: Number(e.target.value) })}
             className="mt-1 w-full accent-[rgb(var(--accent))]" aria-valuetext={pct(weights[key])} />
      <p className="text-xs text-subtle">{help}</p>
    </div>
  );
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">Opportunity Score <Tag kind="Exploratory" /></span>}
          subtitle="Exploratory indicator, not a prediction of success. Scores cuisine × location pairs from rating quality, engagement and low saturation."
          actions={calc}>
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <div className="space-y-4">
          {slider("rating", "Weighted-rating percentile", "Higher weighted rating of the pair's listings")}
          {slider("engagement", "Median-votes percentile", "More reviews per listing (online engagement)")}
          {slider("low_saturation", "Low-saturation percentile", "1 − percentile of listing count (fewer competitors listed)")}
          <button className="btn-ghost btn-sm" onClick={() => setWeights({ rating: 40, engagement: 30, low_saturation: 30 })}>Reset to 40 / 30 / 30</button>
          <pre className="code text-2xs">{`score = 100 × (w1·WR_pct + w2·votes_pct
              + w3·(1 − listings_pct))
pct = (rank − 1) / (n − 1) among eligible pairs`}</pre>
          <p className="text-xs text-subtle">Eligible pairs need at least {d?.opportunity.min_n ?? 8} rated listings. Weights are normalized to sum to 100%.</p>
        </div>
        <div className="min-w-0">
          <Section result={d?.opportunity}>{(rows) => (
            <div className="-mx-4 max-h-80 overflow-auto">
              <table className="table-base">
                <thead className="sticky top-0"><tr><th className="num">#</th><th>Cuisine</th><th>Location</th><th className="num">Score</th><th className="num">WR</th><th className="num">Median votes</th><th className="num">Listings</th></tr></thead>
                <tbody>{rows.slice(0, 25).map((r, i) => (
                  <tr key={`${r.location}-${r.cuisine}`}><td className="num text-subtle">{i + 1}</td><td className="font-medium">{String(r.cuisine)}</td><td>{String(r.location)}</td>
                    <td className="num font-semibold">{fmtNum(r.score, 1)}</td><td className="num">{fmtNum(r.weighted_rating, 3)}</td><td className="num">{fmtInt(r.median_votes)}</td><td className="num">{fmtInt(r.listings)}</td></tr>
                ))}</tbody>
              </table>
              <p className="mt-2 px-4 text-xs text-subtle">Showing top {Math.min(25, rows.length)} of {rows.length} eligible pairs.</p>
            </div>
          )}</Section>
          {d?.sensitivity && (
            <div className="mt-4">
              <p className="mb-2 text-sm font-semibold text-ink">Sensitivity: top 5 under three weightings</p>
              <div className="grid gap-3 md:grid-cols-3">
                {d.sensitivity.map((s) => (
                  <div key={s.scenario} className="rounded-lg border border-line p-3">
                    <p className="text-xs font-semibold text-muted">{s.scenario}</p>
                    <ol className="mt-1 space-y-0.5 text-xs">{s.top.map((t, i) => (
                      <li key={i} className="flex justify-between gap-2"><span className="truncate text-ink">{i + 1}. {t.cuisine}, {t.location}</span><span className="tabular-nums text-muted">{fmtNum(t.score, 0)}</span></li>
                    ))}</ol>
                  </div>
                ))}
              </div>
              <div className="mt-3"><Note>Pairs that appear in all three lists are more robust to the choice of weights. Validate with field research (footfall, rents, competitor visits) before any decision.</Note></div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}


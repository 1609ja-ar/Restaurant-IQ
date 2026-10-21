import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, ChevronLeft, ChevronRight, LayoutGrid, List, Star } from "lucide-react";
import { analysisParams, api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useFilters } from "../hooks/useFilters";
import { fmtBool, fmtInt, fmtMoney, fmtNum, fmtRating } from "../lib/format";
import type { AnalysisContext, Prior, Row } from "../lib/types";
import { FilterBar } from "../components/FilterBar";
import { ContextLine } from "./Dashboard";
import { Assumptions, Card, Drawer, EmptyState, ErrorState, NoDataset, PageHeader, Segmented, Skeleton, Spinner, StatRow } from "../components/ui";

interface ListResponse { context: AnalysisContext; total: number; page: number; pages: number; page_size: number; items: Row[] }
type SortKey = "weighted_rating" | "rating" | "votes" | "name" | "cost";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "weighted_rating", label: "Weighted rating" }, { value: "rating", label: "Rating" },
  { value: "votes", label: "Votes" }, { value: "name", label: "Name" }, { value: "cost", label: "Cost" },
];

const list = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v == null ? "N/A" : String(v));

export default function Explorer() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const { filters, reset } = useFilters();
  const [sort, setSort] = useState<SortKey>("weighted_rating");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [view, setView] = useState<"table" | "grid">("table");
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => setPage(1), [filters, sort, order, ds]);

  const q = useQuery({
    queryKey: ["restaurants", ds, filters, sort, order, page],
    queryFn: () => api<ListResponse>("/restaurants", { params: analysisParams(ds, filters, { sort, order, page, page_size: 50 }) }),
    enabled: !!ds,
    placeholderData: keepPreviousData,
  });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="Explorer" description="Search, filter and inspect individual restaurants." /><NoDataset /></>);
  const d = q.data;
  const costCur = active.data.currencies.length === 1 ? active.data.currencies[0] : null;

  return (
    <>
      <PageHeader title="Explorer" description="Search, filter, sort and inspect individual restaurants. Results are paginated on the server (50 per page)." />
      <FilterBar datasetId={ds} showSearch />
      {d && <ContextLine ctx={d.context} />}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor="sort" className="text-sm text-muted">Sort by</label>
        <select id="sort" className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <button className="btn-secondary" onClick={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))} aria-label={`Sort ${order === "asc" ? "descending" : "ascending"}`}>
          {order === "desc" ? <ArrowDownWideNarrow className="h-4 w-4" aria-hidden /> : <ArrowUpNarrowWide className="h-4 w-4" aria-hidden />}
          {order === "desc" ? "High to low" : "Low to high"}
        </button>
        <span className="ml-auto" />
        {q.isFetching && <Spinner label="Updating" />}
        <Segmented label="View" value={view} onChange={setView} options={[
          { value: "table", label: "Table", icon: <List className="h-3.5 w-3.5" aria-hidden /> },
          { value: "grid", label: "Grid", icon: <LayoutGrid className="h-3.5 w-3.5" aria-hidden /> },
        ]} />
      </div>

      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {!d && q.isLoading && <Skeleton className="h-96" />}
      {d && d.total === 0 && (
        <div className="card"><EmptyState title="No restaurants match" message="Try a different search or remove some filters."
                                           action={<button className="btn-secondary" onClick={reset}>Clear filters</button>} /></div>
      )}
      {d && d.total > 0 && (view === "table" ? (
        <Card bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead><tr><th>Restaurant</th><th>Location</th><th>Cuisines</th><th className="num">Rating</th><th className="num">Weighted</th><th className="num">Votes</th><th className="num">Cost</th><th>Tier</th></tr></thead>
              <tbody>
                {d.items.map((r) => (
                  <tr key={String(r.rid)} className="cursor-pointer" onClick={() => setSelected(Number(r.rid))}>
                    <td className="max-w-[14rem]">
                      <button className="truncate text-left font-medium text-ink hover:text-accent-ink" onClick={(e) => { e.stopPropagation(); setSelected(Number(r.rid)); }}>
                        {String(r.restaurant_name ?? `Row ${r.rid}`)}
                      </button>
                      <p className="truncate text-xs text-subtle">{list(r.restaurant_type)}</p>
                    </td>
                    <td className="whitespace-nowrap text-muted">{String(r.location ?? "N/A")}</td>
                    <td className="max-w-[14rem] truncate text-muted" title={list(r.cuisines)}>{list(r.cuisines)}</td>
                    <td className="num">{r.is_unrated ? <span className="text-subtle">Unrated</span> : fmtNum(r.rating, 1)}</td>
                    <td className="num">{fmtRating(r.weighted_rating)}</td>
                    <td className="num">{fmtInt(r.review_count)}</td>
                    <td className="num">{fmtMoney(r.cost, (r.currency as string) ?? costCur)}{r.cost_outlier ? <span className="ml-1 text-2xs text-warning" title="IQR cost outlier">outlier</span> : null}</td>
                    <td className="text-muted">{String(r.price_tier ?? "N/A")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {d.items.map((r) => (
            <button key={String(r.rid)} onClick={() => setSelected(Number(r.rid))} className="card p-4 text-left transition hover:border-line-strong hover:shadow-pop">
              <p className="truncate font-semibold text-ink">{String(r.restaurant_name ?? `Row ${r.rid}`)}</p>
              <p className="truncate text-xs text-subtle">{String(r.location ?? "N/A")} · {list(r.restaurant_type)}</p>
              <p className="mt-2 line-clamp-2 min-h-[2.5rem] text-sm text-muted">{list(r.cuisines)}</p>
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="flex items-center gap-1 font-semibold tabular-nums text-ink"><Star className="h-3.5 w-3.5 text-subtle" aria-hidden />
                  {r.is_unrated ? "Unrated" : fmtNum(r.rating, 1)}<span className="font-normal text-subtle">({fmtInt(r.review_count)} votes)</span></span>
                <span className="tabular-nums text-muted">{fmtMoney(r.cost, (r.currency as string) ?? costCur)}</span>
              </div>
            </button>
          ))}
        </div>
      ))}

      {d && d.total > 0 && (
        <nav className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm" aria-label="Pagination">
          <span className="text-muted">Showing {((d.page - 1) * d.page_size + 1).toLocaleString()}–{Math.min(d.page * d.page_size, d.total).toLocaleString()} of {d.total.toLocaleString()}</span>
          <div className="flex items-center gap-2">
            <button className="btn-secondary btn-sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={d.page <= 1}><ChevronLeft className="h-4 w-4" aria-hidden /> Previous</button>
            <span className="tabular-nums text-muted">Page {d.page} of {d.pages}</span>
            <button className="btn-secondary btn-sm" onClick={() => setPage((p) => Math.min(d.pages, p + 1))} disabled={d.page >= d.pages}>Next <ChevronRight className="h-4 w-4" aria-hidden /></button>
          </div>
        </nav>
      )}

      {selected !== null && <DetailDrawer rid={selected} datasetId={ds} costCur={costCur} onClose={() => setSelected(null)} />}
      <Assumptions items={[
        "Rows shown are analysis rows: duplicates and invalid rows are excluded (see the Data page).",
        "Missing values are shown as N/A; 'Unrated' means the source had no usable rating.",
        "Sorting places missing values last in both directions.",
        "Weighted rating uses the dataset-wide prior, so a restaurant's value does not change with filters.",
      ]} />
    </>
  );
}

function DetailDrawer({ rid, datasetId, costCur, onClose }: { rid: number; datasetId?: string; costCur: string | null; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["restaurant", datasetId, rid],
    queryFn: () => api<{ restaurant: Row; extras: string[]; prior: Prior }>(`/restaurants/${rid}`, { params: { dataset_id: datasetId } }),
  });
  const r = q.data?.restaurant;
  return (
    <Drawer open onClose={onClose} title={r ? String(r.restaurant_name ?? `Row ${rid}`) : "Restaurant details"}>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorState error={q.error} />}
      {r && (
        <div className="space-y-5">
          <div>
            <p className="label">Ratings</p>
            <StatRow label="Rating (0–5)" value={r.is_unrated ? "Unrated" : fmtNum(r.rating, 2)} />
            <StatRow label="Source rating text" value={String(r.rating_raw ?? "N/A")} />
            <StatRow label="Weighted rating" value={fmtNum(r.weighted_rating, 3)} />
            <StatRow label="Votes" value={fmtInt(r.review_count)} />
            {q.data?.prior.available && <p className="mt-2 text-xs text-subtle">Weighted with C = {q.data.prior.C?.toFixed(3)}, m = {q.data.prior.m} votes.</p>}
          </div>
          <div>
            <p className="label">Listing</p>
            <StatRow label="Location" value={String(r.location ?? "N/A")} />
            <StatRow label="Address" value={<span className="whitespace-normal">{String(r.address ?? "N/A")}</span>} />
            <StatRow label="Cuisines" value={<span className="whitespace-normal">{list(r.cuisines)}</span>} />
            <StatRow label="Type" value={list(r.restaurant_type)} />
            <StatRow label="Cost" value={fmtMoney(r.cost, (r.currency as string) ?? costCur)} />
            <StatRow label="Price tier" value={String(r.price_tier ?? "N/A")} />
            <StatRow label="Online order" value={fmtBool(r.online_order)} />
            <StatRow label="Table booking" value={fmtBool(r.table_booking)} />
          </div>
          <div>
            <p className="label">Data quality flags</p>
            <StatRow label="Source row" value={fmtInt(r.source_row)} />
            <StatRow label="Included in analysis" value={r.include_in_analysis ? "Yes" : "No"} />
            <StatRow label="Cost outlier (IQR)" value={r.cost_outlier ? "Yes" : "No"} />
            {r.invalid_reason ? <StatRow label="Invalid" value={String(r.invalid_reason)} /> : null}
          </div>
          {q.data && q.data.extras.length > 0 && (
            <div>
              <p className="label">Other source columns</p>
              {q.data.extras.map((k) => <StatRow key={k} label={k} value={<span className="whitespace-normal break-words">{String(r[k] ?? "N/A")}</span>} />)}
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}

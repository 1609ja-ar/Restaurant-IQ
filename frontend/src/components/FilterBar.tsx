import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw, Search, SlidersHorizontal, X } from "lucide-react";
import { api } from "../lib/api";
import { useDebounced, useFilters } from "../hooks/useFilters";
import { activeFilterCount, type Filters } from "../lib/filters";
import { fmtMoney } from "../lib/format";
import type { FilterOptions } from "../lib/types";
import { MultiSelect } from "./ui";

export function useFilterOptions(datasetId: string | undefined) {
  return useQuery({
    queryKey: ["filter-options", datasetId],
    queryFn: () => api<FilterOptions>("/filters/options", { params: { dataset_id: datasetId } }),
    enabled: !!datasetId,
    staleTime: 60_000,
  });
}

function TriSelect({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean | null) => void }) {
  const id = `tri-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="sr-only">{label}</label>
      <select id={id} className={`input ${value !== null ? "border-accent/60" : ""}`} value={value === null ? "" : String(value)}
              onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}>
        <option value="">{label}: any</option>
        <option value="true">{label}: Yes</option>
        <option value="false">{label}: No</option>
      </select>
    </div>
  );
}

/** Compact BI filter bar. Every analytical request sends these filters to the backend,
 *  which applies them identically to KPIs, charts, tables and tests. */
export function FilterBar({ datasetId, showSearch = false }: { datasetId: string | undefined; showSearch?: boolean }) {
  const { filters, update, reset } = useFilters();
  const opts = useFilterOptions(datasetId);
  const o = opts.data;
  const [search, setSearch] = useState(filters.search);
  const debounced = useDebounced(search, 300);
  useEffect(() => { if (debounced !== filters.search) update({ search: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSearch(filters.search); }, [filters.search]);
  const [ratingMin, setRatingMin] = useState(filters.rating_min?.toString() ?? "");
  const [ratingMax, setRatingMax] = useState(filters.rating_max?.toString() ?? "");
  useEffect(() => { setRatingMin(filters.rating_min?.toString() ?? ""); setRatingMax(filters.rating_max?.toString() ?? ""); }, [filters.rating_min, filters.rating_max]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const count = activeFilterCount(filters);

  const commitRating = () => {
    const parse = (s: string) => { const n = Number(s); return s.trim() === "" || !Number.isFinite(n) ? null : Math.min(5, Math.max(0, n)); };
    update({ rating_min: parse(ratingMin), rating_max: parse(ratingMax) });
  };
  const cutoffs = o?.price_tier_cutoffs ? Object.entries(o.price_tier_cutoffs) : [];

  return (
    <div className="card mb-6 p-3">
      <div className="flex items-center justify-between gap-2 md:hidden">
        <button className="btn-secondary btn-sm" onClick={() => setMobileOpen((v) => !v)} aria-expanded={mobileOpen}>
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden /> Filters {count > 0 && `(${count})`}
        </button>
        {count > 0 && <button className="btn-ghost btn-sm" onClick={reset}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Reset</button>}
      </div>
      <div className={`${mobileOpen ? "mt-3 grid" : "hidden"} grid-cols-1 gap-2 sm:grid-cols-2 md:mt-0 md:grid md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5`}>
        {showSearch && (
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden />
            <input className="input pl-9" placeholder="Search restaurant name" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search restaurant name" />
          </div>
        )}
        <MultiSelect label="Location" options={o?.location ?? []} value={filters.location} onChange={(v) => update({ location: v })} />
        <MultiSelect label="Cuisine" options={o?.cuisine ?? []} value={filters.cuisine} onChange={(v) => update({ cuisine: v })} />
        <MultiSelect label="Restaurant type" options={o?.restaurant_type ?? []} value={filters.restaurant_type} onChange={(v) => update({ restaurant_type: v })} />
        <MultiSelect label="Price tier" options={(o?.price_tier ?? []).map((t) => ({ value: t }))} value={filters.price_tier} onChange={(v) => update({ price_tier: v })} />
        <div className="flex items-center gap-1.5" role="group" aria-label="Rating range">
          <input className="input" inputMode="decimal" placeholder="Rating min" aria-label="Minimum rating (0 to 5)" value={ratingMin}
                 onChange={(e) => setRatingMin(e.target.value)} onBlur={commitRating} onKeyDown={(e) => e.key === "Enter" && commitRating()} disabled={!o?.has_rating} />
          <span className="text-subtle" aria-hidden>–</span>
          <input className="input" inputMode="decimal" placeholder="max" aria-label="Maximum rating (0 to 5)" value={ratingMax}
                 onChange={(e) => setRatingMax(e.target.value)} onBlur={commitRating} onKeyDown={(e) => e.key === "Enter" && commitRating()} disabled={!o?.has_rating} />
        </div>
        {o?.has_online_order && <TriSelect label="Online order" value={filters.online_order} onChange={(v) => update({ online_order: v })} />}
        {o?.has_table_booking && <TriSelect label="Table booking" value={filters.table_booking} onChange={(v) => update({ table_booking: v })} />}
        {o && o.currencies.length > 1 && (
          <select className="input" aria-label="Currency" value={filters.currency ?? ""} onChange={(e) => update({ currency: e.target.value || null })}>
            <option value="">Currency: all (costs N/A)</option>
            {o.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        <label className="flex items-center gap-2 rounded-lg px-1 text-sm text-muted">
          <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--accent))]" checked={filters.exclude_outliers}
                 onChange={(e) => update({ exclude_outliers: e.target.checked })} />
          Exclude cost outliers
        </label>
      </div>
      {count > 0 && <ActiveChips filters={filters} update={update} reset={reset} />}
      {cutoffs.length > 0 && filters.price_tier.length > 0 && (
        <p className="mt-2 text-xs text-subtle">
          Price tiers: {cutoffs.map(([cur, c]) => `Budget ≤ ${fmtMoney(c.budget_max, cur)}, Mid-range ≤ ${fmtMoney(c.mid_max, cur)}, Premium above`).join("; ")}.
        </p>
      )}
    </div>
  );
}

function ActiveChips({ filters, update, reset }: { filters: Filters; update: (p: Partial<Filters>) => void; reset: () => void }) {
  const chips: { label: string; clear: () => void }[] = [];
  const multi = (key: "location" | "cuisine" | "restaurant_type" | "price_tier") =>
    filters[key].forEach((v) => chips.push({ label: v, clear: () => update({ [key]: filters[key].filter((x) => x !== v) } as Partial<Filters>) }));
  multi("location"); multi("cuisine"); multi("restaurant_type"); multi("price_tier");
  if (filters.rating_min !== null || filters.rating_max !== null)
    chips.push({ label: `Rating ${filters.rating_min ?? 0}–${filters.rating_max ?? 5}`, clear: () => update({ rating_min: null, rating_max: null }) });
  if (filters.online_order !== null) chips.push({ label: `Online order: ${filters.online_order ? "Yes" : "No"}`, clear: () => update({ online_order: null }) });
  if (filters.table_booking !== null) chips.push({ label: `Table booking: ${filters.table_booking ? "Yes" : "No"}`, clear: () => update({ table_booking: null }) });
  if (filters.currency) chips.push({ label: `Currency: ${filters.currency}`, clear: () => update({ currency: null }) });
  if (filters.search.trim()) chips.push({ label: `Name: "${filters.search.trim()}"`, clear: () => update({ search: "" }) });
  if (filters.exclude_outliers) chips.push({ label: "Cost outliers excluded", clear: () => update({ exclude_outliers: false }) });
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
      {chips.map((c) => (
        <button key={c.label} onClick={c.clear} className="chip border-accent/40 bg-accent-soft text-accent-ink hover:brightness-95" aria-label={`Remove filter ${c.label}`}>
          {c.label}<X className="h-3 w-3" aria-hidden />
        </button>
      ))}
      <button className="btn-ghost btn-sm ml-auto hidden md:inline-flex" onClick={reset}><RotateCcw className="h-3.5 w-3.5" aria-hidden /> Reset all</button>
    </div>
  );
}

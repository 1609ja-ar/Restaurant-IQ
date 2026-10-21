import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { EMPTY_FILTERS, type Filters } from "../lib/filters";

/** Filters are shared by Dashboard, Explorer, Market Analysis and Reports, so they survive
 *  navigation. They reset automatically when the active dataset version changes. */
interface FilterState {
  filters: Filters;
  setFilters: (f: Filters) => void;
  update: (patch: Partial<Filters>) => void;
  reset: () => void;
}

const FilterContext = createContext<FilterState | null>(null);

export function FilterProvider({ datasetId, children }: { datasetId: string | undefined; children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  useEffect(() => setFilters(EMPTY_FILTERS), [datasetId]);
  const update = useCallback((patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch })), []);
  const reset = useCallback(() => setFilters(EMPTY_FILTERS), []);
  const value = useMemo(() => ({ filters, setFilters, update, reset }), [filters, update, reset]);
  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterState {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used inside FilterProvider");
  return ctx;
}

/** Debounce a fast-changing value (search box) before it hits the API. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

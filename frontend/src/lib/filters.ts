export interface Filters {
  location: string[];
  cuisine: string[];
  restaurant_type: string[];
  price_tier: string[];
  rating_min: number | null;
  rating_max: number | null;
  online_order: boolean | null;
  table_booking: boolean | null;
  currency: string | null;
  search: string;
  exclude_outliers: boolean;
}

export const EMPTY_FILTERS: Filters = {
  location: [], cuisine: [], restaurant_type: [], price_tier: [], rating_min: null, rating_max: null,
  online_order: null, table_booking: null, currency: null, search: "", exclude_outliers: false,
};

export function filtersToParams(f: Filters): Record<string, string | number | boolean | string[] | null | undefined> {
  return {
    location: f.location, cuisine: f.cuisine, restaurant_type: f.restaurant_type, price_tier: f.price_tier,
    rating_min: f.rating_min, rating_max: f.rating_max,
    online_order: f.online_order === null ? undefined : f.online_order,
    table_booking: f.table_booking === null ? undefined : f.table_booking,
    currency: f.currency, search: f.search.trim() || undefined,
    exclude_outliers: f.exclude_outliers || undefined,
  };
}

/** Same shape the backend's Filters.from_dict accepts (used by report requests). */
export function filtersToBody(f: Filters): Record<string, unknown> {
  return { ...f, search: f.search.trim() || null };
}

export function activeFilterCount(f: Filters): number {
  return f.location.length + f.cuisine.length + f.restaurant_type.length + f.price_tier.length +
    (f.rating_min !== null || f.rating_max !== null ? 1 : 0) + (f.online_order !== null ? 1 : 0) +
    (f.table_booking !== null ? 1 : 0) + (f.currency ? 1 : 0) + (f.search.trim() ? 1 : 0) + (f.exclude_outliers ? 1 : 0);
}

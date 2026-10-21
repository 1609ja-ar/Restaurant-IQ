/** API response shapes (mirrors backend/app/main.py). */

export interface Reconciliation {
  raw_rows: number;
  blank_rows_removed: number;
  duplicates_removed: number;
  rows_after_dedup: number;
  invalid_rows_excluded: number;
  invalid_breakdown: { rating_outside_scale: number; negative_votes: number; negative_cost: number };
  rows_used_in_analysis: number;
  unrated_rows_in_analysis: number | null;
  rated_rows_in_analysis: number | null;
  cost_outliers_flagged: number;
  dedup_rule: string;
  duplicate_examples: { removed_source_row: number; kept_source_row: number }[];
  balanced: boolean;
}

export interface Feature { available: boolean; requires: string }
export interface Capabilities {
  fields: Record<string, boolean>;
  features: Record<string, Feature>;
  currencies: string[];
}

export interface DatasetSummary {
  dataset_id: string;
  version: number;
  name: string;
  is_demo: boolean;
  created_at: string;
  source_filename: string | null;
  source_upload_id?: string | null;
  reconciliation: Reconciliation;
  capabilities: Capabilities;
  rating_scale: { min: number; max: number | null; normalized_to: string | null };
  price_unit: string;
  currencies: string[];
  file_type?: string;
}

export interface QualityRow {
  column: string;
  field: string | null;
  completeness_pct: number | null;
  uniqueness_pct: number | null;
  validity_pct: number | null;
  non_null: number;
  valid: number | null;
  note: string;
}

export interface LogEntry { step: string; detail: string; rows: number }

export interface DatasetDetail extends DatasetSummary {
  quality: QualityRow[];
  log: LogEntry[];
  mapping: Record<string, string>;
  extras: string[];
  location_source: string | null;
  price_tier_cutoffs: Record<string, { budget_max: number; mid_max: number }>;
  cost_outlier_bounds: Record<string, { lower: number; upper: number }>;
  import_settings: Record<string, unknown>;
}

export interface VersionRow {
  dataset_id: string;
  version: number;
  name: string;
  created_at: string;
  is_demo: boolean;
  source_filename: string | null;
  rows_used: number;
}

export interface ColumnProfile {
  name: string;
  detected_type: string;
  null_count: number;
  null_pct: number | null;
  sample_values: string[];
}

export interface MappingSuggestion {
  source_column: string;
  suggested_field: string | null;
  confidence: "high" | "medium" | null;
  score: number;
  reason: string;
}

export interface UploadProfile {
  file_type: "csv" | "xlsx";
  encoding: string | null;
  delimiter: string | null;
  sheet: string | null;
  row_count: number;
  blank_row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  preview: Record<string, string | null>[];
  suggested_mapping: MappingSuggestion[];
  rating_scale: { max: number | null; min: number; source: string; confident: boolean } | null;
  suggested_price_unit: string;
  warnings: string[];
}

export interface UploadResponse { upload_id: string; filename: string; size_bytes: number; profile: UploadProfile }

export interface ValidateResponse {
  reconciliation: Reconciliation;
  quality: QualityRow[];
  log: LogEntry[];
  capabilities: Capabilities;
  rating_scale: { min: number; max: number | null };
  price_tier_cutoffs: Record<string, { budget_max: number; mid_max: number }>;
  currencies: string[];
}

export interface Prior { available: boolean; C?: number; m?: number; m_source?: string; n_rated?: number; reason?: string }

export interface AnalysisContext {
  dataset_id: string;
  dataset_name: string;
  version: number;
  is_demo: boolean;
  filters: string[];
  sample_size: number;
  total_rows: number;
  settings: { min_group_n: number; opportunity_min_n: number };
  prior: Prior;
  price_unit: string | null;
  generated_at: string;
}

export interface Kpi {
  id: string;
  label: string;
  definition: string;
  unit: string | null;
  value: number | null;
  available: boolean;
  reason: string | null;
}

export interface Result<T> { available: boolean; data: T | null; reason: string | null; label?: string; caveat?: string | null }

export interface Finding { tag: "Descriptive" | "Statistical" | "Suggestion"; title: string; detail: string; source: string }

export type Row = Record<string, unknown>;

export interface DashboardData {
  context: AnalysisContext;
  kpis: Kpi[];
  charts: Record<string, Result<unknown>>;
  cost_unit: string | null;
  findings: Finding[];
  outlier_impact: OutlierImpact | null;
  capabilities: Capabilities;
}

export interface OutlierImpact {
  with_outliers: { n: number; mean: number | null; median: number | null; std: number | null };
  without_outliers: { n: number; mean: number | null; median: number | null; std: number | null };
  outliers: number;
}

export interface FilterOptions {
  location: { value: string; count: number }[];
  cuisine: { value: string; count: number }[];
  restaurant_type: { value: string; count: number }[];
  price_tier: string[];
  price_tier_cutoffs: Record<string, { budget_max: number; mid_max: number }>;
  currencies: string[];
  has_online_order: boolean;
  has_table_booking: boolean;
  has_rating: boolean;
}

export interface CalculationDetail {
  id: string;
  label: string;
  definition: string;
  caveat: string | null;
  pandas_code: string;
  filter_code: string;
  sql: string;
  filters: string[];
  sample_size: number;
  dataset_id: string;
  tolerance: string;
  available: boolean;
  reason: string | null;
  match: boolean | null;
  mismatches: string[];
  pandas_result: unknown;
  sql_result: unknown;
  prior: Prior | null;
}

export interface Settings { min_group_n: number; opportunity_min_n: number; bayes_m_override: number | null; revision: number }

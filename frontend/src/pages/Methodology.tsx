import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { fmtNum } from "../lib/format";
import type { Prior } from "../lib/types";
import { Assumptions, Card, PageHeader, SectionTitle } from "../components/ui";

const DICTIONARY: [string, string, string][] = [
  ["rid / source_row", "integer", "Row number in the raw file (1-based, header excluded). Used as the restaurant id."],
  ["restaurant_name, address", "text", "Trimmed text; blank means not provided."],
  ["location", "text", "Most granular geographic label available (locality, else city, else region)."],
  ["cuisines, restaurant_type", "list of text", "Split on , | ; then trimmed, title-cased and de-duplicated."],
  ["rating", "number 0-5", "Parsed rating normalized to 0-5 from the confirmed source scale; null = unrated."],
  ["rating_source / rating_raw", "number / text", "Rating on the original scale / exactly as written in the file."],
  ["review_count", "number >= 0", "Votes or reviews. Negative = invalid. Unparseable = null."],
  ["cost", "number >= 0", "Listed price in the dataset currency and unit (for two, per person...). Null when missing."],
  ["currency", "text", "Per-row currency column, or the dataset-level currency chosen at import."],
  ["online_order, table_booking", "true / false / null", "Yes/No values; anything else stays null (unknown), never assumed No."],
  ["weighted_rating", "number 0-5", "Bayesian weighted rating (see formula). Null when rating or votes are missing."],
  ["price_tier", "Budget / Mid-range / Premium", "Cost terciles (33rd and 67th percentiles) of analysis rows, per currency."],
  ["is_unrated", "boolean", "Rating missing or unparseable (NEW, -, blank)."],
  ["rating_invalid, votes_invalid, cost_invalid, is_invalid", "boolean", "Out-of-range values; invalid rows are excluded from analysis."],
  ["cost_outlier", "boolean", "Outside Q1 - 1.5 IQR to Q3 + 1.5 IQR (per currency). Flag only."],
  ["include_in_analysis", "boolean", "False for invalid rows. Duplicates are removed from the cleaned file entirely."],
];

const RULES = [
  ["1. Ratings", "'4.1/5' becomes 4.1. 'NEW', '-', blank or unparseable become null and are flagged unrated. Unrated rows stay for counts, cost and location analysis but are excluded from rating statistics."],
  ["2. Costs", "'1,200' becomes 1200; currency symbols are removed. Missing costs stay null (never 0). IQR outliers are flagged, not deleted; the Dashboard shows statistics with and without them."],
  ["3. Duplicates", "Key = normalized restaurant name + address (case, spacing and punctuation ignored). The row with the most votes is kept; ties keep the earliest row. Without a name column only exact duplicate rows are removed."],
  ["4. Lists", "Cuisines and types are split on commas (also | and ;), trimmed and title-cased. A restaurant is counted once per cuisine in cuisine charts."],
  ["5. Yes/No", "Yes/Y/True/1 → true; No/N/False/0 → false; anything else → null."],
  ["6. Invalid values", "Ratings outside the source scale, negative votes and negative costs mark the row invalid. Invalid rows are kept (flagged) in the cleaned file but excluded from all analysis."],
  ["7. Reconciliation", "Raw rows − blank rows − duplicates − invalid rows = rows used in analysis. Unrated rows are a subset of rows used."],
  ["8. Quality metrics", "Completeness = non-empty / rows; uniqueness = distinct / non-empty; validity = parseable and in range / non-empty."],
  ["9. Lineage", "The original upload is stored unchanged. Each import stores its mapping, settings, log and quality report as a new version."],
];

const FORMULAS = [
  ["Mean / median rating", "mean(R) and median(R) over rated restaurants (R on the 0-5 scale)."],
  ["Weighted (Bayesian) rating", "WR = v/(v+m)·R + m/(v+m)·C. v = votes, R = rating, C = mean rating of rated rows in the whole version, m = median of positive vote counts (or the Settings override). v = 0 gives WR = C; v + m = 0 gives WR = R; missing rating or votes gives null."],
  ["Group weighted rating", "Mean of restaurant-level WR within the group; a group is reliable only with n ≥ minimum group size (default 10)."],
  ["Listing share", "Listings with the cuisine / restaurants in the selection × 100 (shares sum to more than 100%)."],
  ["Location quotient (saturation)", "(cuisine listings in location / location listings) ÷ (cuisine listings overall / all listings). LQ > 1 = over-represented."],
  ["Price tiers", "Budget ≤ P33 < Mid-range ≤ P67 < Premium, computed per currency on analysis rows."],
  ["Spearman rho", "Pearson correlation of average ranks on rows with both values; requires n ≥ 10 and two non-constant variables. p-value from scipy.stats.spearmanr."],
  ["Mann-Whitney U", "Two-sided test comparing ratings of Yes vs No groups (unknown excluded), each n ≥ 10. Effect size r = 2U/(n₁n₂) − 1 (rank-biserial)."],
  ["Opportunity Score", "100 × (w₁·WR percentile + w₂·median-votes percentile + w₃·(1 − listings percentile)) over cuisine × location pairs with ≥ 8 rated listings; percentile = (rank − 1)/(n − 1). Default weights 40/30/30. Exploratory indicator, not a prediction of success."],
  ["Skewness / IQR", "Bias-corrected sample skewness; IQR = P75 − P25 (linear interpolation, same in pandas and DuckDB)."],
];

export default function Methodology() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const dash = useQuery({
    queryKey: ["dashboard-prior", ds],
    queryFn: () => api<{ context: { prior: Prior; settings: { min_group_n: number; opportunity_min_n: number } } }>("/dashboard", { params: { dataset_id: ds } }),
    enabled: !!ds,
  });
  const prior = dash.data?.context.prior;
  return (
    <>
      <PageHeader title="Methodology" description="How RestaurantIQ cleans data and computes every metric. The same definitions are used on every page, in exports and in reports." />
      {prior?.available && (
        <Card title="Active dataset parameters" subtitle={`Dataset ${ds}`}>
          <p className="text-sm text-muted">Bayesian prior: C = {fmtNum(prior.C, 4)} (mean rating of {prior.n_rated?.toLocaleString()} rated restaurants), m = {fmtNum(prior.m, 1)} votes ({prior.m_source}). Minimum group size {dash.data?.context.settings.min_group_n}; Opportunity Score minimum {dash.data?.context.settings.opportunity_min_n}.</p>
        </Card>
      )}
      <SectionTitle>Data dictionary (canonical fields)</SectionTitle>
      <Card bodyClass="p-0">
        <div className="overflow-x-auto"><table className="table-base"><thead><tr><th>Field</th><th>Type</th><th>Meaning and rules</th></tr></thead>
          <tbody>{DICTIONARY.map(([f, t, d]) => <tr key={f}><td className="font-mono text-xs">{f}</td><td className="whitespace-nowrap text-muted">{t}</td><td className="text-muted">{d}</td></tr>)}</tbody></table></div>
        <p className="border-t border-line px-4 py-3 text-xs text-subtle">Every field is optional. Unmapped source columns are preserved unchanged. Features that need a missing field are disabled with an explanation.</p>
      </Card>
      <SectionTitle>Cleaning rules</SectionTitle>
      <div className="grid gap-3 md:grid-cols-2">{RULES.map(([t, d]) => <Card key={t} title={t}><p className="text-sm text-muted">{d}</p></Card>)}</div>
      <SectionTitle>Formulas</SectionTitle>
      <Card bodyClass="p-0">
        <div className="overflow-x-auto"><table className="table-base"><thead><tr><th>Metric</th><th>Definition</th></tr></thead>
          <tbody>{FORMULAS.map(([m, d]) => <tr key={m}><td className="whitespace-nowrap font-medium">{m}</td><td className="text-muted">{d}</td></tr>)}</tbody></table></div>
      </Card>
      <SectionTitle>Calculation integrity</SectionTitle>
      <Card>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
          <li>The backend is the single source of truth; the frontend only formats numbers for display.</li>
          <li>Every KPI, chart and table has a pandas implementation and an equivalent DuckDB SQL query. "Show calculation" displays the real pandas source and executes the SQL with the active filters, then compares results (relative and absolute tolerance 1e-9).</li>
          <li>Values are computed at full precision and rounded only for display.</li>
          <li>Missing values are N/A, never zero. Mixed currencies are never combined.</li>
          <li>An independent notebook (notebooks/validation.ipynb) re-implements cleaning and KPIs and compares them with API values (PASS/FAIL).</li>
        </ul>
      </Card>
      <Assumptions items={[
        "Data is a snapshot of listings; it says nothing about trends unless a validated date field exists.",
        "Ratings are user-generated platform scores and may be biased or manipulated.",
        "No revenue, footfall, demand or profit data is available; never read ratings or listing counts as these.",
        "Costs are approximate listed prices in the stated unit (for example 'for two').",
        "All statistical results are observational; correlation is not causation and group differences can be confounded.",
        "Sample data is synthetic and illustrative only.",
      ]} />
    </>
  );
}

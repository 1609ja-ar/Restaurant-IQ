import type { Filters } from "../lib/filters";
import { fmtKpi } from "../lib/format";
import type { Kpi } from "../lib/types";
import { ShowCalculation } from "./ShowCalculation";

const COST_IDS = new Set(["mean_cost", "median_cost"]);

export function KpiCard({ kpi, datasetId, filters }: { kpi: Kpi; datasetId: string | undefined; filters: Filters }) {
  const isCost = COST_IDS.has(kpi.id);
  const value = kpi.available ? fmtKpi(kpi.value, kpi.unit, isCost) : "N/A";
  const precise = typeof kpi.value === "number" ? kpi.value.toLocaleString("en-US", { maximumFractionDigits: 6 }) : undefined;
  return (
    <div className="card flex min-h-[8.5rem] flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-muted">{kpi.label}</p>
        <ShowCalculation calcId={kpi.id} datasetId={datasetId} filters={filters} compact />
      </div>
      <p className={`mt-1 text-2xl font-semibold tracking-tight tabular-nums ${kpi.available ? "text-ink" : "text-subtle"}`} title={precise}>
        {value}
        {kpi.available && kpi.unit === "/5" && <span className="ml-1 text-sm font-normal text-subtle">/ 5</span>}
      </p>
      <p className="mt-auto pt-2 text-xs leading-snug text-subtle">{kpi.available ? kpi.definition : kpi.reason}</p>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search, X } from "lucide-react";
import { api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useDebounced } from "../hooks/useFilters";
import { fmtBool, fmtFraction, fmtInt, fmtMoney, fmtRating } from "../lib/format";
import type { Row } from "../lib/types";
import { useFilterOptions } from "../components/FilterBar";
import { GroupedBars } from "../components/charts";
import { Assumptions, Card, EmptyState, ErrorState, NoDataset, Note, PageHeader, Segmented, Skeleton, Spinner, Tag } from "../components/ui";

type Kind = "cuisine" | "location" | "restaurant";
interface Metric { key: string; label: string; format: "int" | "rating" | "money" | "pct" | "text" | "bool" }
interface Entity { id: string; name: string; values: Record<string, unknown>; sample_size: number; sufficient_sample: boolean | null }
interface CompareResponse { kind: Kind; metrics: Metric[]; entities: Entity[]; summary: string[]; caveats: string[]; cost_unit: string | null }

function fmtValue(v: unknown, f: Metric["format"], cur: string | null): string {
  if (f === "int") return fmtInt(v);
  if (f === "rating") return fmtRating(v);
  if (f === "money") return fmtMoney(v, cur);
  if (f === "pct") return fmtFraction(v);
  if (f === "bool") return fmtBool(v);
  if (Array.isArray(v)) return v.join(", ");
  return v == null ? "N/A" : String(v);
}

export default function Compare() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const opts = useFilterOptions(ds);
  const [kind, setKind] = useState<Kind>("cuisine");
  const [items, setItems] = useState<{ id: string; label: string }[]>([]);
  useEffect(() => setItems([]), [kind, ds]);

  const q = useQuery({
    queryKey: ["compare", ds, kind, items.map((i) => i.id)],
    queryFn: () => api<CompareResponse>("/compare", { method: "POST", body: { dataset_id: ds, kind, items: items.map((i) => i.id) } }),
    enabled: !!ds && items.length >= 2,
  });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="Compare" description="Compare restaurants, cuisines or locations side by side." /><NoDataset /></>);

  const add = (id: string, label: string) => {
    if (!id || items.length >= 4 || items.some((i) => i.id === id)) return;
    setItems([...items, { id, label }]);
  };
  const choices = kind === "cuisine" ? opts.data?.cuisine ?? [] : kind === "location" ? opts.data?.location ?? [] : [];
  const fieldAvailable = kind === "restaurant" ? true : kind === "cuisine" ? (opts.data?.cuisine.length ?? 0) > 0 : (opts.data?.location.length ?? 0) > 0;

  return (
    <>
      <PageHeader title="Compare" description="Compare 2 to 4 restaurants, cuisines or locations using the same calculations as the Dashboard. Comparisons describe listings; they do not explain causes." />
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <div className="shrink-0">
            <p className="label">Compare</p>
            <Segmented<Kind> label="Comparison type" value={kind} onChange={setKind} options={[
              { value: "cuisine", label: "Cuisines" }, { value: "location", label: "Locations" }, { value: "restaurant", label: "Restaurants" }]} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="label">Items ({items.length} of 4, at least 2)</p>
            {!fieldAvailable ? <Note>This dataset has no {kind} column to compare.</Note> : kind === "restaurant" ? (
              <RestaurantPicker datasetId={ds} disabled={items.length >= 4} onPick={(rid, name) => add(rid, name)} />
            ) : (
              <div className="flex gap-2">
                <label htmlFor="pick" className="sr-only">Choose a {kind}</label>
                <select id="pick" className="input" value="" onChange={(e) => add(e.target.value, e.target.value)} disabled={items.length >= 4}>
                  <option value="">{items.length >= 4 ? "Maximum of 4 items" : `Add a ${kind}`}</option>
                  {choices.filter((c) => !items.some((i) => i.id === c.value)).map((c) => <option key={c.value} value={c.value}>{c.value} ({c.count})</option>)}
                </select>
              </div>
            )}
            {items.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {items.map((i) => (
                  <button key={i.id} className="chip border-accent/40 bg-accent-soft text-accent-ink" onClick={() => setItems(items.filter((x) => x.id !== i.id))} aria-label={`Remove ${i.label}`}>
                    {i.label}<X className="h-3 w-3" aria-hidden />
                  </button>
                ))}
                <button className="btn-ghost btn-sm" onClick={() => setItems([])}>Clear</button>
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="mt-6 space-y-4">
        {items.length < 2 && <div className="card"><EmptyState icon={<Plus className="h-5 w-5" aria-hidden />} title="Pick at least two items" message="Results appear as soon as two items are selected." /></div>}
        {q.isLoading && items.length >= 2 && <Skeleton className="h-64" />}
        {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
        {q.data && <CompareResult data={q.data} />}
      </div>
      <Assumptions items={[
        "Cuisine and location profiles use exactly the same KPI functions as the Dashboard filtered to that cuisine or location.",
        "Online-ordering and table-booking shares are computed over restaurants where the value is known.",
        "Small groups are flagged; their averages can change a lot with a few restaurants.",
        "No causal claims: a higher rating does not mean a cuisine or location causes better outcomes.",
      ]} />
    </>
  );
}

function RestaurantPicker({ datasetId, onPick, disabled }: { datasetId?: string; onPick: (rid: string, name: string) => void; disabled: boolean }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const res = useQuery({
    queryKey: ["compare-search", datasetId, dq],
    queryFn: () => api<{ items: Row[] }>("/compare/search", { params: { dataset_id: datasetId, q: dq } }),
    enabled: !!datasetId,
  });
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" aria-hidden />
        <input className="input pl-9" placeholder="Search restaurants by name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search restaurants" disabled={disabled} />
      </div>
      <ul className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-line">
        {res.isLoading && <li className="p-2"><Spinner /></li>}
        {res.data?.items.length === 0 && <li className="p-3 text-sm text-subtle">No matching restaurants</li>}
        {res.data?.items.map((r) => (
          <li key={String(r.rid)}>
            <button className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-3 disabled:opacity-50" disabled={disabled}
                    onClick={() => onPick(String(r.rid), `${r.restaurant_name ?? `Row ${r.rid}`} (${r.location ?? "N/A"})`)}>
              <span className="truncate text-ink">{String(r.restaurant_name ?? `Row ${r.rid}`)} <span className="text-subtle">· {String(r.location ?? "N/A")}</span></span>
              <span className="shrink-0 tabular-nums text-xs text-muted">{fmtRating(r.rating)} · {fmtInt(r.review_count)} votes</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CompareResult({ data }: { data: CompareResponse }) {
  const cur = data.cost_unit;
  const ratingKeys = data.kind === "restaurant" ? ["rating", "weighted_rating"] : ["mean_rating", "median_rating", "weighted_rating"];
  const costKeys = data.kind === "restaurant" ? ["cost"] : ["median_cost", "mean_cost"];
  const chart = (keys: string[]) => keys.map((k) => ({
    metric: data.metrics.find((m) => m.key === k)?.label ?? k,
    ...Object.fromEntries(data.entities.map((e, i) => [`e${i}`, typeof e.values[k] === "number" ? e.values[k] : null])),
  }));
  const series = data.entities.map((e, i) => ({ key: `e${i}`, label: e.name }));
  const hasCost = useMemo(() => data.entities.some((e) => costKeys.some((k) => typeof e.values[k] === "number")), [data]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Card title="Summary" subtitle="Templated from the computed values below">
        <ul className="space-y-2">{data.summary.map((s) => <li key={s} className="flex gap-2 text-sm"><Tag kind="Descriptive" /><span className="text-ink">{s}</span></li>)}</ul>
      </Card>
      <Card title="Side-by-side metrics" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead><tr><th>Metric</th>{data.entities.map((e) => <th key={e.id} className="num normal-case">{e.name}{e.sufficient_sample === false && <span className="ml-1 text-2xs text-subtle">(small n)</span>}</th>)}</tr></thead>
            <tbody>{data.metrics.map((m) => (
              <tr key={m.key}><td className="font-medium">{m.label}</td>
                {data.entities.map((e) => <td key={e.id} className={m.format === "text" ? "max-w-[14rem] text-right" : "num"}>{fmtValue(e.values[m.key], m.format, cur)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Ratings (0–5)" subtitle="Same axis for every series">
          <GroupedBars data={chart(ratingKeys)} series={series} labelKey="metric" format={(v) => v.toFixed(2)} />
        </Card>
        {hasCost && (
          <Card title={`Cost${cur ? ` (${cur})` : ""}`} subtitle="Shown separately from ratings (different units)">
            <GroupedBars data={chart(costKeys)} series={series} labelKey="metric" format={(v) => fmtMoney(v, cur)} />
          </Card>
        )}
      </div>
      <Note>{data.caveats.join(" ")}</Note>
    </>
  );
}

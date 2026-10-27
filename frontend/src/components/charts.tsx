/** Recharts wrappers with one consistent, theme-aware style.
 *  Colors are read from CSS variables (validated palette in index.css), so charts switch
 *  with the theme. Text always uses ink tokens; series colors only fill marks. */
import { useMemo, type ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis, type TooltipProps,
} from "recharts";
import { useTheme } from "../hooks/useTheme";
import { fmtCompact } from "../lib/format";

export interface ChartColors {
  series: string[]; muted: string; tiers: string[]; grid: string; axis: string; surface: string; text: string;
}

export function useChartColors(): ChartColors {
  const { theme } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const v = (n: string) => css.getPropertyValue(n).trim();
    return {
      series: [v("--chart-1"), v("--chart-2"), v("--chart-3"), v("--chart-4")],
      muted: v("--chart-muted"),
      tiers: [v("--chart-tier-1"), v("--chart-tier-2"), v("--chart-tier-3")],
      grid: v("--chart-grid"), axis: v("--chart-axis"), surface: v("--chart-surface"),
      text: `rgb(${v("--text")})`,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
}

export function TooltipBox({ title, rows }: { title?: ReactNode; rows: { label: string; value: ReactNode; color?: string }[] }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      {title && <p className="mb-1 max-w-[16rem] font-semibold text-ink">{title}</p>}
      {rows.map((r) => (
        <p key={r.label} className="flex items-center justify-between gap-4 text-muted">
          <span className="flex items-center gap-1.5">
            {r.color && <span className="h-2 w-2 rounded-full" style={{ background: r.color }} aria-hidden />}{r.label}
          </span>
          <span className="font-semibold tabular-nums text-ink">{r.value}</span>
        </p>
      ))}
    </div>
  );
}

const axisTick = (c: ChartColors) => ({ fill: c.axis, fontSize: 11 });

const CATEGORY_AXIS_WIDTH = 132;

/** Single-line category label. Recharts wraps long labels onto several lines, which made
 *  names like "Bannerghatta Road" collide with the neighbouring bar's label. We truncate to
 *  the axis width instead and keep the full name in a native tooltip. */
function CategoryTick({ x, y, payload, color }: { x?: number; y?: number; payload?: { value: unknown }; color: string }) {
  const full = String(payload?.value ?? "");
  const maxChars = Math.floor((CATEGORY_AXIS_WIDTH - 12) / 6.4);
  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <title>{full}</title>
      <text x={-4} y={0} dy={4} textAnchor="end" fill={color} fontSize={11}>{truncate(full, maxChars)}</text>
    </g>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Horizontal bar chart for ranked categories (long labels stay readable). */
export function HBarChart<T extends Record<string, unknown>>({ data, labelKey, valueKey, format, tooltip, colorFor, height }: {
  data: T[]; labelKey: keyof T & string; valueKey: keyof T & string; format: (v: number) => string;
  tooltip: (row: T) => { title: string; rows: { label: string; value: string }[] };
  colorFor?: (row: T) => string; height?: number;
}) {
  const c = useChartColors();
  const h = height ?? Math.max(160, data.length * 26 + 30);
  return (
    <div style={{ height: h }} role="img" aria-label={`Bar chart of ${valueKey} by ${labelKey}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 4 }} barCategoryGap={4}>
          <CartesianGrid horizontal={false} stroke={c.grid} />
          <XAxis type="number" tick={axisTick(c)} tickFormatter={(v) => fmtCompact(v)} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey={labelKey} width={CATEGORY_AXIS_WIDTH} tick={(props) => <CategoryTick {...props} color={c.axis} />}
                 axisLine={{ stroke: c.grid }} tickLine={false} interval={0} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.5 }}
                   content={({ active, payload }: TooltipProps<number, string>) => {
                     if (!active || !payload?.length) return null;
                     const t = tooltip(payload[0].payload as T);
                     return <TooltipBox title={t.title} rows={t.rows} />;
                   }} />
          <Bar dataKey={valueKey} radius={[0, 4, 4, 0]} maxBarSize={18}
               label={{ position: "right", fill: c.axis, fontSize: 11, formatter: (v: number) => format(v) }}>
            {data.map((row, i) => <Cell key={i} fill={colorFor ? colorFor(row) : c.series[0]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Vertical histogram-style bars (rating distribution). */
export function VBarChart<T extends Record<string, unknown>>({ data, labelKey, valueKey, tooltip, height = 240 }: {
  data: T[]; labelKey: keyof T & string; valueKey: keyof T & string; height?: number;
  tooltip: (row: T) => { title: string; rows: { label: string; value: string }[] };
}) {
  const c = useChartColors();
  return (
    <div style={{ height }} role="img" aria-label={`Column chart of ${valueKey} by ${labelKey}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis dataKey={labelKey} tick={axisTick(c)} axisLine={{ stroke: c.grid }} tickLine={false} interval="preserveStartEnd" minTickGap={8} />
          <YAxis tick={axisTick(c)} tickFormatter={(v) => fmtCompact(v)} axisLine={false} tickLine={false} width={40} allowDecimals={false} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.5 }}
                   content={({ active, payload }: TooltipProps<number, string>) => {
                     if (!active || !payload?.length) return null;
                     const t = tooltip(payload[0].payload as T);
                     return <TooltipBox title={t.title} rows={t.rows} />;
                   }} />
          <Bar dataKey={valueKey} fill={c.series[0]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Donut for a 2-3 part whole (price tiers) with an ordinal ramp and a legend. */
export function Donut({ data, total, centerLabel }: { data: { label: string; value: number }[]; total: number; centerLabel: string }) {
  const c = useChartColors();
  return (
    <div className="flex flex-col items-center gap-3 sm:flex-row">
      <div className="relative h-48 w-48 shrink-0" role="img" aria-label="Donut chart of price tier shares">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="label" innerRadius="62%" outerRadius="95%" paddingAngle={1}
                 stroke={c.surface} strokeWidth={2} isAnimationActive={false}>
              {data.map((_, i) => <Cell key={i} fill={c.tiers[i % 3]} />)}
            </Pie>
            <Tooltip content={({ active, payload }: TooltipProps<number, string>) => {
              if (!active || !payload?.length) return null;
              const p = payload[0];
              return <TooltipBox title={String(p.name)} rows={[{ label: "Restaurants", value: Number(p.value).toLocaleString() },
                { label: "Share", value: `${((Number(p.value) / total) * 100).toFixed(1)}%` }]} />;
            }} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-semibold tabular-nums text-ink">{total.toLocaleString()}</span>
          <span className="text-2xs text-subtle">{centerLabel}</span>
        </div>
      </div>
      <ul className="w-full space-y-2 text-sm">
        {data.map((d, i) => (
          <li key={d.label} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-muted">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c.tiers[i % 3] }} aria-hidden />{d.label}
            </span>
            <span className="tabular-nums text-ink">{d.value.toLocaleString()} <span className="text-subtle">({((d.value / total) * 100).toFixed(1)}%)</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ScatterPlot({ points, xKey, yKey, xLabel, yLabel, logX, nameKey, height = 280 }: {
  points: Record<string, unknown>[]; xKey: string; yKey: string; xLabel: string; yLabel: string; logX?: boolean;
  nameKey?: string; height?: number;
}) {
  const c = useChartColors();
  // log scale cannot show 0, so plot votes + 1 and say so in the axis label
  const data = useMemo(() => points.map((p) => ({ ...p, __x: logX ? Number(p[xKey]) + 1 : Number(p[xKey]) })), [points, xKey, logX]);
  return (
    <div style={{ height }} role="img" aria-label={`Scatter plot of ${yLabel} against ${xLabel}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 0 }}>
          <CartesianGrid stroke={c.grid} />
          <XAxis type="number" dataKey="__x" scale={logX ? "log" : "auto"} domain={logX ? [1, "auto"] : ["auto", "auto"]}
                 tick={axisTick(c)} tickFormatter={(v) => fmtCompact(v)} axisLine={{ stroke: c.grid }} tickLine={false}
                 label={{ value: xLabel, position: "insideBottom", offset: -14, fill: c.axis, fontSize: 11 }} allowDataOverflow />
          <YAxis type="number" dataKey={yKey} domain={[0, 5]} tick={axisTick(c)} axisLine={false} tickLine={false} width={36}
                 label={{ value: yLabel, angle: -90, position: "insideLeft", offset: 12, fill: c.axis, fontSize: 11 }} />
          <ZAxis range={[28, 28]} />
          <Tooltip cursor={{ strokeDasharray: "3 3", stroke: c.axis }}
                   content={({ active, payload }: TooltipProps<number, string>) => {
                     if (!active || !payload?.length) return null;
                     const p = payload[0].payload as Record<string, unknown>;
                     return <TooltipBox title={nameKey ? String(p[nameKey] ?? "Restaurant") : undefined}
                                        rows={[{ label: yLabel, value: Number(p[yKey]).toFixed(1) },
                                               { label: "Votes", value: Number(p[xKey]).toLocaleString() }]} />;
                   }} />
          <Scatter data={data} fill={c.series[0]} fillOpacity={0.55} stroke={c.surface} strokeWidth={1} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Grouped bars for comparing 2-4 entities across one metric (single axis, fixed slot order). */
export function GroupedBars({ data, series, labelKey, format, height = 260 }: {
  data: Record<string, unknown>[]; series: { key: string; label: string }[]; labelKey: string; format: (v: number) => string; height?: number;
}) {
  const c = useChartColors();
  return (
    <div style={{ height }} role="img" aria-label="Grouped bar comparison">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis dataKey={labelKey} tick={axisTick(c)} axisLine={{ stroke: c.grid }} tickLine={false} interval={0} tickFormatter={(v) => truncate(String(v), 16)} />
          <YAxis tick={axisTick(c)} tickFormatter={(v) => fmtCompact(v)} axisLine={false} tickLine={false} width={44} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.5 }}
                   content={({ active, payload, label }: TooltipProps<number, string>) => {
                     if (!active || !payload?.length) return null;
                     return <TooltipBox title={String(label)} rows={payload.map((p, i) => ({ label: String(p.name), value: p.value == null ? "N/A" : format(Number(p.value)), color: c.series[i % 4] }))} />;
                   }} />
          <Legend wrapperStyle={{ fontSize: 12, color: c.axis }} iconType="circle" iconSize={8} />
          {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={c.series[i % 4]} radius={[4, 4, 0, 0]} maxBarSize={36} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

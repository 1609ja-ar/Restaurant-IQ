/** Display formatting only. Values arrive at full precision from the backend; we round here. */
export const NA = "N/A";

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function fmtInt(v: unknown): string {
  return isNum(v) ? Math.round(v).toLocaleString("en-US") : NA;
}

export function fmtNum(v: unknown, digits = 2): string {
  return isNum(v) ? v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : NA;
}

export function fmtRating(v: unknown): string {
  return isNum(v) ? v.toFixed(2) : NA;
}

export function fmtPct(v: unknown, digits = 1): string {
  return isNum(v) ? `${v.toFixed(digits)}%` : NA;
}

export function fmtFraction(v: unknown, digits = 1): string {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : NA;
}

const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£", JPY: "¥" };

export function fmtMoney(v: unknown, currency?: string | null, digits = 0): string {
  if (!isNum(v)) return NA;
  const n = v.toLocaleString(currency === "INR" ? "en-IN" : "en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
  if (!currency) return n;
  const sym = SYMBOLS[currency];
  return sym ? `${sym}${n}` : `${n} ${currency}`;
}

/** Compact axis labels (1.2k, 3.4M); tooltips use the precise formatters. */
export function fmtCompact(v: unknown): string {
  if (!isNum(v)) return NA;
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

export function fmtBool(v: unknown): string {
  return v === true ? "Yes" : v === false ? "No" : "Unknown";
}

export function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

export function fmtP(v: unknown): string {
  if (!isNum(v)) return NA;
  return v < 0.001 ? "< 0.001" : v.toFixed(3);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return NA;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Format a KPI value according to its unit. */
export function fmtKpi(value: unknown, unit: string | null | undefined, isCost: boolean): string {
  if (isCost) return fmtMoney(value, unit ?? null);
  if (unit === "/5") return fmtRating(value);
  return fmtInt(value);
}

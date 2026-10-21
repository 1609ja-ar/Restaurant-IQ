import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Check, ChevronDown, Database, Info, Loader2, Search, X } from "lucide-react";

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, subtitle, actions, children, className = "", bodyClass = "p-4" }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`card flex min-w-0 flex-col ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
        </header>
      )}
      <div className={`min-w-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 mt-8 flex items-baseline justify-between gap-3 first:mt-0">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-subtle">{children}</h2>
      {hint && <span className="text-xs text-subtle">{hint}</span>}
    </div>
  );
}

export function SampleBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-2xs font-semibold text-warning">
      <Info className="h-3 w-3" aria-hidden /> Sample data — illustrative only
    </span>
  );
}

const TAG_STYLES: Record<string, string> = {
  Descriptive: "bg-info-soft text-info",
  Statistical: "bg-success-soft text-success",
  Suggestion: "bg-accent-soft text-accent-ink",
  Exploratory: "bg-warning-soft text-warning",
};

export function Tag({ kind }: { kind: string }) {
  return <span className={`inline-flex shrink-0 rounded-md px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide ${TAG_STYLES[kind] ?? "bg-surface-3 text-muted"}`}>{kind}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-3 ${className}`} aria-hidden />;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label ?? "Loading"}
    </span>
  );
}

export function EmptyState({ title, message, action, icon }: { title: string; message?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <div className="mb-1 rounded-full bg-surface-3 p-3 text-subtle">{icon ?? <Search className="h-5 w-5" aria-hidden />}</div>
      <p className="text-sm font-semibold text-ink">{title}</p>
      {message && <p className="max-w-md text-sm text-muted">{message}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft p-4" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink">Could not load this data</p>
        <p className="mt-0.5 text-sm text-muted break-words">{msg}</p>
      </div>
      {onRetry && <button className="btn-secondary btn-sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Unavailable({ reason, compact = false }: { reason: string | null | undefined; compact?: boolean }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg border border-dashed border-line-strong bg-surface-2 text-sm text-muted ${compact ? "p-2" : "p-4"}`}>
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-subtle" aria-hidden />
      <span><span className="font-medium text-ink">N/A. </span>{reason ?? "Not available for this dataset."}</span>
    </div>
  );
}

export function Note({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warning" }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg p-3 text-xs leading-relaxed ${tone === "warning" ? "bg-warning-soft text-ink" : "bg-surface-2 text-muted"}`}>
      {tone === "warning" ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> : <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden />}
      <div>{children}</div>
    </div>
  );
}

export function Assumptions({ items }: { items: string[] }) {
  return (
    <details className="card group mt-8 p-4">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold text-ink">
        <span className="flex items-center gap-2"><Info className="h-4 w-4 text-subtle" aria-hidden /> Assumptions &amp; Limitations</span>
        <ChevronDown className="h-4 w-4 text-subtle transition group-open:rotate-180" aria-hidden />
      </summary>
      <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-muted">
        {items.map((t) => <li key={t}>{t}</li>)}
      </ul>
    </details>
  );
}

export function NoDataset() {
  return (
    <div className="card">
      <EmptyState
        icon={<Database className="h-5 w-5" aria-hidden />}
        title="No dataset loaded yet"
        message="Load the sample dataset or import your own CSV/XLSX file to start analyzing."
        action={<Link to="/data" className="btn-primary">Go to Data</Link>}
      />
    </div>
  );
}

/** Accessible modal dialog: focus moves in, Escape closes, focus returns to the trigger. */
export function Dialog({ open, onClose, title, children, wide = false }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) {
        const nodes = ref.current.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
        if (!nodes.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
           onMouseDown={(e) => e.stopPropagation()}
           className={`card flex max-h-[92vh] w-full flex-col shadow-pop outline-none ${wide ? "sm:max-w-4xl" : "sm:max-w-lg"} rounded-b-none sm:rounded-xl`}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 id={titleId} className="text-base font-semibold text-ink">{title}</h2>
          <button className="btn-ghost btn-sm p-1.5" onClick={onClose} aria-label="Close dialog"><X className="h-4 w-4" /></button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

/** Slide-in side panel (detail drawer). */
export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onMouseDown={onClose}>
      <aside ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
             className="flex h-full w-full max-w-md flex-col border-l border-line bg-surface shadow-pop outline-none">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
          <button className="btn-ghost btn-sm p-1.5" onClick={onClose} aria-label="Close details"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

/** Multi-select dropdown with search; keyboard accessible (checkbox list). */
export function MultiSelect({ label, options, value, onChange, disabled }: {
  label: string; options: { value: string; count?: number }[]; value: string[]; onChange: (v: string[]) => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const shown = options.filter((o) => o.value.toLowerCase().includes(q.toLowerCase())).slice(0, 200);
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div className="relative" ref={ref}>
      <button type="button" className={`input flex items-center justify-between gap-2 text-left ${value.length ? "border-accent/60" : ""}`}
              aria-haspopup="listbox" aria-expanded={open} aria-controls={id} disabled={disabled || !options.length}
              onClick={() => setOpen((o) => !o)}>
        <span className="truncate">
          <span className="text-muted">{label}</span>
          {value.length > 0 && <span className="ml-1.5 rounded bg-accent-soft px-1.5 text-xs font-semibold text-accent-ink">{value.length}</span>}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-subtle" aria-hidden />
      </button>
      {open && (
        <div id={id} className="card absolute left-0 z-30 mt-1 w-72 max-w-[85vw] p-2 shadow-pop">
          <input className="input mb-2" placeholder={`Search ${label.toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} autoFocus aria-label={`Search ${label}`} />
          <ul role="listbox" aria-multiselectable="true" aria-label={label} className="max-h-64 overflow-y-auto">
            {shown.map((o) => {
              const selected = value.includes(o.value);
              return (
                <li key={o.value}>
                  <button type="button" role="option" aria-selected={selected} onClick={() => toggle(o.value)}
                          className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-3 ${selected ? "text-ink" : "text-muted"}`}>
                    <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${selected ? "border-accent bg-accent text-on-accent" : "border-line-strong"}`}>
                      {selected && <Check className="h-3 w-3" aria-hidden />}
                    </span>
                    <span className="flex-1 truncate">{o.value}</span>
                    {o.count !== undefined && <span className="text-xs tabular-nums text-subtle">{o.count.toLocaleString()}</span>}
                  </button>
                </li>
              );
            })}
            {!shown.length && <li className="px-2 py-3 text-sm text-subtle">No matches</li>}
          </ul>
          {value.length > 0 && <button className="btn-ghost btn-sm mt-1 w-full" onClick={() => onChange([])}>Clear {label.toLowerCase()}</button>}
        </div>
      )}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string; icon?: ReactNode }[]; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${value === o.value ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"}`}>
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  );
}

export function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-1.5 text-sm last:border-0">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium tabular-nums text-ink">{value}</span>
    </div>
  );
}

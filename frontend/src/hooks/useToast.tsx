import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; title: string; message?: string }

const ToastContext = createContext<{ push: (kind: Kind, title: string, message?: string) => void } | null>(null);

const STYLES: Record<Kind, { icon: typeof Info; cls: string; label: string }> = {
  success: { icon: CheckCircle2, cls: "text-success", label: "Success" },
  error: { icon: AlertTriangle, cls: "text-danger", label: "Error" },
  info: { icon: Info, cls: "text-info", label: "Info" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback((kind: Kind, title: string, message?: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, kind, title, message }]);
    window.setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4500);
  }, [dismiss]);
  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite" role="status">
        {toasts.map((t) => {
          const s = STYLES[t.kind];
          const Icon = s.icon;
          return (
            <div key={t.id} className="card flex items-start gap-3 p-3 shadow-pop">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${s.cls}`} aria-label={s.label} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink">{t.title}</p>
                {t.message && <p className="mt-0.5 text-sm text-muted break-words">{t.message}</p>}
              </div>
              <button className="btn-ghost btn-sm -m-1 p-1" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx.push;
}

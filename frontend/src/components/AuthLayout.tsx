import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, Eye, EyeOff, Info } from "lucide-react";
import { ThemeToggle } from "./Layout";

/** Centered card used by the login and signup pages (works in light and dark themes, phone to desktop). */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-bg px-4 py-10">
      <div className="absolute right-3 top-3"><ThemeToggle /></div>
      <main className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          <svg viewBox="0 0 32 32" className="h-12 w-12" aria-hidden>
            <rect width="32" height="32" rx="8" fill="#0B1B3A" />
            <path d="M8.5 7v6.5a2.7 2.7 0 0 0 2 2.6V25" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />
            <path d="M10.5 7v5M12.5 7v6.5a2.7 2.7 0 0 1-2 2.6" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />
            <rect x="16.5" y="17" width="3" height="8" rx="1" fill="#FF6B57" />
            <rect x="21" y="12" width="3" height="13" rx="1" fill="#FF6B57" />
            <rect x="25.5" y="8" width="3" height="17" rx="1" fill="#FF8A79" />
          </svg>
          <p className="mt-3 text-xl font-semibold tracking-tight text-ink">Restaurant<span className="text-accent-ink">IQ</span></p>
          <p className="mt-1 text-sm text-muted">Turn Restaurant Data Into Smarter Business Decisions.</p>
        </div>
        <section className="card p-6 sm:p-8" aria-labelledby="auth-title">
          <h1 id="auth-title" className="text-lg font-semibold text-ink">{title}</h1>
          <p className="mt-1 text-sm text-muted">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </section>
        {footer && <div className="mt-5 text-center text-sm text-muted">{footer}</div>}
      </main>
    </div>
  );
}

export function Banner({ tone, children }: { tone: "error" | "info"; children: ReactNode }) {
  const Icon = tone === "error" ? AlertTriangle : Info;
  return (
    <div role={tone === "error" ? "alert" : "status"}
         className={`mb-4 flex items-start gap-2 rounded-lg border p-3 text-sm ${tone === "error" ? "border-danger/30 bg-danger-soft text-ink" : "border-info/30 bg-info-soft text-ink"}`}>
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone === "error" ? "text-danger" : "text-info"}`} aria-hidden />
      <span>{children}</span>
    </div>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string | null; hint?: string };

/** Labelled input with inline error wired to aria-invalid / aria-describedby. */
export function Field({ label, error, hint, id, ...props }: FieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  const describedBy = [error ? `${fid}-error` : null, hint ? `${fid}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="mb-4">
      <label htmlFor={fid} className="label">{label}</label>
      <input id={fid} className={`input ${error ? "border-danger focus:border-danger focus:ring-danger/30" : ""}`}
             aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...props} />
      {hint && !error && <p id={`${fid}-hint`} className="mt-1 text-xs text-subtle">{hint}</p>}
      {error && <p id={`${fid}-error`} className="mt-1 text-xs font-medium text-danger">{error}</p>}
    </div>
  );
}

/** Password input with a show/hide toggle. */
export function PasswordField({ label, error, hint, id, ...props }: FieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  const [visible, setVisible] = useState(false);
  const describedBy = [error ? `${fid}-error` : null, hint ? `${fid}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="mb-4">
      <label htmlFor={fid} className="label">{label}</label>
      <div className="relative">
        <input id={fid} type={visible ? "text" : "password"}
               className={`input pr-10 ${error ? "border-danger focus:border-danger focus:ring-danger/30" : ""}`}
               aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...props} />
        <button type="button" onClick={() => setVisible((v) => !v)} aria-pressed={visible}
                aria-label={visible ? "Hide password" : "Show password"} title={visible ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-subtle hover:text-ink">
          {visible ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </button>
      </div>
      {hint && !error && <p id={`${fid}-hint`} className="mt-1 text-xs text-subtle">{hint}</p>}
      {error && <p id={`${fid}-error`} className="mt-1 text-xs font-medium text-danger">{error}</p>}
    </div>
  );
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return "Use at least 8 characters.";
  if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return "Include at least one letter and one number.";
  if (new TextEncoder().encode(pw).length > 72) return "Use at most 72 bytes.";
  return null;
}

import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { FlaskConical, Loader2, LogIn } from "lucide-react";
import { ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout, Banner, EMAIL_RE, Field, PasswordField } from "../components/AuthLayout";

type From = { pathname: string; search?: string } | undefined;

export function destination(state: unknown): string {
  const from = (state as { from?: From } | null)?.from;
  if (!from || from.pathname === "/login" || from.pathname === "/signup") return "/";
  return `${from.pathname}${from.search ?? ""}`;
}

export default function Login() {
  const { user, status, config, notice, clearNotice, login, demoLogin } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState<"form" | "demo" | null>(null);

  if (status === "ready" && user) return <Navigate to={destination(location.state)} replace />;

  const go = () => navigate(destination(location.state), { replace: true });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pending) return;                                  // no double submit
    const next: typeof errors = {};
    if (!email.trim()) next.email = "Enter your email address.";
    else if (!EMAIL_RE.test(email.trim())) next.email = "Enter a valid email address, for example name@example.com.";
    if (!password) next.password = "Enter your password.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setFailure(null);
    clearNotice();
    setPending("form");
    try {
      await login(email.trim(), password);
      go();
    } catch (err) {
      setFailure(err instanceof ApiError ? err.message : "Sign-in failed. Please try again.");
      setPending(null);
    }
  };

  const demo = async () => {
    if (pending) return;
    setFailure(null);
    clearNotice();
    setPending("demo");
    try {
      await demoLogin();
      go();
    } catch (err) {
      setFailure(err instanceof ApiError ? err.message : "The demo account is not available.");
      setPending(null);
    }
  };

  return (
    <AuthLayout title="Sign in" subtitle="Use your RestaurantIQ account to continue."
      footer={config?.allow_registration ? <>No account yet? <Link to="/signup" state={location.state} className="font-semibold text-accent-ink hover:underline">Create one</Link></> : null}>
      {notice && !failure && <Banner tone="info">{notice}</Banner>}
      {failure && <Banner tone="error">{failure}</Banner>}
      <form onSubmit={submit} noValidate>
        <Field label="Email" type="email" name="email" autoComplete="email" autoFocus required inputMode="email"
               value={email} onChange={(e) => { setEmail(e.target.value); setErrors((x) => ({ ...x, email: undefined })); }}
               error={errors.email} disabled={pending !== null} />
        <PasswordField label="Password" name="password" autoComplete="current-password" required
                       value={password} onChange={(e) => { setPassword(e.target.value); setErrors((x) => ({ ...x, password: undefined })); }}
                       error={errors.password} disabled={pending !== null} />
        <button type="submit" className="btn-primary mt-2 w-full py-2.5" disabled={pending !== null} aria-busy={pending === "form"}>
          {pending === "form" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <LogIn className="h-4 w-4" aria-hidden />}
          {pending === "form" ? "Signing in..." : "Sign in"}
        </button>
      </form>
      {config?.demo_available && (
        <>
          <div className="my-5 flex items-center gap-3 text-xs text-subtle" aria-hidden><span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" /></div>
          <button type="button" className="btn-secondary w-full py-2.5" onClick={demo} disabled={pending !== null} aria-busy={pending === "demo"}>
            {pending === "demo" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FlaskConical className="h-4 w-4" aria-hidden />}
            Use demo account
          </button>
          <p className="mt-2 text-center text-xs text-subtle">Demo account for trying the app. Do not store real data in it.</p>
        </>
      )}
    </AuthLayout>
  );
}

import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Loader2, UserPlus } from "lucide-react";
import { ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout, Banner, EMAIL_RE, Field, PasswordField, passwordProblem } from "../components/AuthLayout";
import { FullScreenLoader } from "../components/ProtectedRoute";
import { destination } from "./Login";

interface Errors { name?: string; email?: string; password?: string; confirm?: string }

export default function Signup() {
  const { user, status, config, register } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (status === "ready" && user) return <Navigate to={destination(location.state)} replace />;
  if (!config) return <FullScreenLoader label="Loading" />;
  if (!config.allow_registration) return <Navigate to="/login" replace state={location.state} />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pending) return;
    const next: Errors = {};
    if (!name.trim()) next.name = "Enter your name.";
    if (!email.trim()) next.email = "Enter your email address.";
    else if (!EMAIL_RE.test(email.trim())) next.email = "Enter a valid email address, for example name@example.com.";
    const pw = passwordProblem(password);
    if (pw) next.password = pw;
    if (confirm !== password) next.confirm = "The passwords do not match.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setFailure(null);
    setPending(true);
    try {
      await register(name.trim(), email.trim(), password);
      navigate(destination(location.state), { replace: true });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not create the account. Please try again.";
      if (err instanceof ApiError && err.status === 409) setErrors({ email: msg });
      else setFailure(msg);
      setPending(false);
    }
  };

  const clear = (k: keyof Errors) => setErrors((x) => ({ ...x, [k]: undefined }));

  return (
    <AuthLayout title="Create your account" subtitle="Your datasets are private to your account."
      footer={<>Already have an account? <Link to="/login" state={location.state} className="font-semibold text-accent-ink hover:underline">Sign in</Link></>}>
      {failure && <Banner tone="error">{failure}</Banner>}
      <form onSubmit={submit} noValidate>
        <Field label="Name" name="name" autoComplete="name" autoFocus required maxLength={80}
               value={name} onChange={(e) => { setName(e.target.value); clear("name"); }} error={errors.name} disabled={pending} />
        <Field label="Email" type="email" name="email" autoComplete="email" required inputMode="email"
               value={email} onChange={(e) => { setEmail(e.target.value); clear("email"); }} error={errors.email} disabled={pending} />
        <PasswordField label="Password" name="new-password" autoComplete="new-password" required
                       hint="At least 8 characters, with at least one letter and one number."
                       value={password} onChange={(e) => { setPassword(e.target.value); clear("password"); }}
                       error={errors.password} disabled={pending} />
        <PasswordField label="Confirm password" name="confirm-password" autoComplete="new-password" required
                       value={confirm} onChange={(e) => { setConfirm(e.target.value); clear("confirm"); }}
                       error={errors.confirm} disabled={pending} />
        <button type="submit" className="btn-primary mt-2 w-full py-2.5" disabled={pending} aria-busy={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <UserPlus className="h-4 w-4" aria-hidden />}
          {pending ? "Creating account..." : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}

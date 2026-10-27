import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "../hooks/useAuth";

export function FullScreenLoader({ label = "Checking your session" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg" role="status" aria-live="polite">
      <span className="flex items-center gap-2 text-sm text-muted">
        <Loader2 className="h-5 w-5 animate-spin text-accent-ink" aria-hidden /> {label}...
      </span>
    </div>
  );
}

/** Renders children only for a signed-in user. Others go to /login and come back here afterwards.
 *  While the session is being checked a loading screen is shown, so protected content never flashes. */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <FullScreenLoader />;
  if (!user) return <Navigate to="/login" replace state={{ from: { pathname: location.pathname, search: location.search } }} />;
  return <>{children}</>;
}

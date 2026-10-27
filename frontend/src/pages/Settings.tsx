import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Monitor, Moon, Sun } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { passwordProblem, PasswordField } from "../components/AuthLayout";
import { useSettings } from "../hooks/useDataset";
import { useTheme } from "../hooks/useTheme";
import { useToast } from "../hooks/useToast";
import type { Settings } from "../lib/types";
import type { ThemePref } from "../lib/theme";
import { Card, ErrorState, PageHeader, Segmented, Skeleton } from "../components/ui";

export default function SettingsPage() {
  const { pref, setPref, theme } = useTheme();
  const settings = useSettings();
  const qc = useQueryClient();
  const toast = useToast();
  const [minN, setMinN] = useState("");
  const [oppN, setOppN] = useState("");
  const [m, setM] = useState("");
  useEffect(() => {
    if (!settings.data) return;
    setMinN(String(settings.data.min_group_n));
    setOppN(String(settings.data.opportunity_min_n));
    setM(settings.data.bayes_m_override === null ? "" : String(settings.data.bayes_m_override));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => api<Settings>("/settings", { method: "PUT", body: {
      min_group_n: Number(minN), opportunity_min_n: Number(oppN),
      ...(m.trim() === "" ? { clear_bayes_m_override: true } : { bayes_m_override: Number(m) }),
    } }),
    onSuccess: () => { qc.invalidateQueries(); toast("success", "Settings saved", "All analyses were recalculated with the new settings."); },
    onError: (e) => toast("error", "Settings not saved", (e as Error).message),
  });
  const valid = Number.isInteger(Number(minN)) && Number(minN) >= 2 && Number.isInteger(Number(oppN)) && Number(oppN) >= 2 && (m.trim() === "" || Number(m) >= 0);

  return (
    <>
      <PageHeader title="Settings" description="Appearance and the analysis thresholds used on every page." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Theme" subtitle={`Currently showing the ${theme} theme. Synchronized with the header toggle.`}>
          <Segmented<ThemePref> label="Theme" value={pref} onChange={setPref} options={[
            { value: "light", label: "Light", icon: <Sun className="h-3.5 w-3.5" aria-hidden /> },
            { value: "dark", label: "Dark", icon: <Moon className="h-3.5 w-3.5" aria-hidden /> },
            { value: "system", label: "System", icon: <Monitor className="h-3.5 w-3.5" aria-hidden /> },
          ]} />
          <p className="mt-3 text-sm text-muted">System follows your operating system's light/dark preference. Your choice is saved in this browser.</p>
        </Card>
        <Card title="Analysis settings" subtitle="Changing these recalculates every KPI, chart, test and report">
          {settings.isLoading && <Skeleton className="h-40" />}
          {settings.isError && <ErrorState error={settings.error} onRetry={() => settings.refetch()} />}
          {settings.data && (
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate(); }}>
              <div>
                <label className="label" htmlFor="min-n">Minimum group size for rankings (n)</label>
                <input id="min-n" className="input" type="number" min={2} max={1000} value={minN} onChange={(e) => setMinN(e.target.value)} />
                <p className="mt-1 text-xs text-subtle">Cuisines, locations and types with fewer rated restaurants are marked "insufficient sample". Default 10.</p>
              </div>
              <div>
                <label className="label" htmlFor="opp-n">Opportunity Score minimum rated listings per pair</label>
                <input id="opp-n" className="input" type="number" min={2} max={1000} value={oppN} onChange={(e) => setOppN(e.target.value)} />
                <p className="mt-1 text-xs text-subtle">Default 8.</p>
              </div>
              <div>
                <label className="label" htmlFor="prior-m">Bayesian prior strength m (votes)</label>
                <input id="prior-m" className="input" type="number" min={0} step="any" placeholder="Automatic: median of positive vote counts" value={m} onChange={(e) => setM(e.target.value)} />
                <p className="mt-1 text-xs text-subtle">Leave blank for the automatic value. Larger m pulls low-vote ratings more strongly toward the dataset mean; m = 0 gives raw ratings.</p>
              </div>
              <button className="btn-primary" type="submit" disabled={!valid || save.isPending}>
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} Save settings
              </button>
              {!valid && <p className="text-xs text-danger">Group sizes must be whole numbers of at least 2; m must be 0 or more.</p>}
            </form>
          )}
        </Card>
      </div>
      <div className="mt-4 max-w-xl"><AccountCard /></div>
    </>
  );
}


/** Account details and password change. Changing the password signs out every other session. */
function AccountCard() {
  const { user } = useAuth();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const change = useMutation({
    mutationFn: () => api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } }),
    onSuccess: () => {
      setCurrent(""); setNext(""); setConfirm("");
      toast("success", "Password changed", "Other devices have been signed out.");
    },
    onError: (e) => {
      const msg = e instanceof ApiError ? e.message : "Could not change the password.";
      if (e instanceof ApiError && e.status === 400) setErrors({ current: msg });
      else toast("error", "Password not changed", msg);
    },
  });
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (change.isPending) return;
    const errs: typeof errors = {};
    if (!current) errs.current = "Enter your current password.";
    const pw = passwordProblem(next);
    if (pw) errs.next = pw;
    if (confirm !== next) errs.confirm = "The passwords do not match.";
    setErrors(errs);
    if (!Object.keys(errs).length) change.mutate();
  };
  if (!user) return null;
  return (
    <Card title="Account" subtitle={`Signed in as ${user.name} (${user.email})${user.is_demo ? " - demo account" : ""}`}>
      <form onSubmit={submit} noValidate>
        <p className="mb-3 text-sm font-medium text-ink">Change password</p>
        <PasswordField label="Current password" autoComplete="current-password" value={current}
                       onChange={(e) => { setCurrent(e.target.value); setErrors((x) => ({ ...x, current: undefined })); }}
                       error={errors.current} disabled={change.isPending} />
        <PasswordField label="New password" autoComplete="new-password" value={next}
                       hint="At least 8 characters, with at least one letter and one number."
                       onChange={(e) => { setNext(e.target.value); setErrors((x) => ({ ...x, next: undefined })); }}
                       error={errors.next} disabled={change.isPending} />
        <PasswordField label="Confirm new password" autoComplete="new-password" value={confirm}
                       onChange={(e) => { setConfirm(e.target.value); setErrors((x) => ({ ...x, confirm: undefined })); }}
                       error={errors.confirm} disabled={change.isPending} />
        <button type="submit" className="btn-primary" disabled={change.isPending}>
          {change.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} Change password
        </button>
      </form>
    </Card>
  );
}

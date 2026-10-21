import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Monitor, Moon, Sun } from "lucide-react";
import { api } from "../lib/api";
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
    </>
  );
}

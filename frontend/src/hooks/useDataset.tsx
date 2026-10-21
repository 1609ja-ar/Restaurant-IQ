import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { DatasetSummary, Settings, VersionRow } from "../lib/types";

/** The active dataset version. Every analytical query includes its id in the query key,
 *  so switching versions refetches everything and never shows another version's numbers. */
export function useActiveDataset() {
  return useQuery({
    queryKey: ["active-dataset"],
    queryFn: () => api<{ active: DatasetSummary | null }>("/datasets/active"),
    select: (d) => d.active,
  });
}

export function useVersions() {
  return useQuery({
    queryKey: ["versions"],
    queryFn: () => api<{ active: string | null; versions: VersionRow[] }>("/datasets"),
  });
}

export function useSetActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (datasetId: string) => api<{ active: DatasetSummary }>("/datasets/active", { method: "PUT", body: { dataset_id: datasetId } }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useLoadDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ active: DatasetSummary }>("/demo/load", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
}

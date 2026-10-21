import { Lightbulb } from "lucide-react";
import type { Finding } from "../lib/types";
import { Card, EmptyState, Tag } from "./ui";

export function FindingsPanel({ findings }: { findings: Finding[] }) {
  return (
    <Card title="Key Findings" subtitle="Generated from the computed results above. Tags show the kind of evidence."
          actions={<div className="hidden gap-1 sm:flex"><Tag kind="Descriptive" /><Tag kind="Statistical" /><Tag kind="Suggestion" /></div>}>
      {findings.length === 0 ? (
        <EmptyState icon={<Lightbulb className="h-5 w-5" aria-hidden />} title="No findings for this selection"
                    message="There is not enough data in the current filters to produce reliable findings." />
      ) : (
        <ul className="divide-y divide-line">
          {findings.map((f, i) => (
            <li key={i} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0 sm:flex-row sm:gap-3">
              <div className="sm:w-28 sm:shrink-0"><Tag kind={f.tag} /></div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{f.title}</p>
                <p className="mt-0.5 text-sm text-muted">{f.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

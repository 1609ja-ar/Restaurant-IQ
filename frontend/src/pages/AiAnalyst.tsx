import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Loader2, Send, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useActiveDataset } from "../hooks/useDataset";
import { useFilterOptions } from "../components/FilterBar";
import { ShowCalculation } from "../components/ShowCalculation";
import { EMPTY_FILTERS } from "../lib/filters";
import { Assumptions, Card, EmptyState, ErrorState, NoDataset, Note, PageHeader, SampleBadge, Skeleton, Tag } from "../components/ui";

interface Suggestion { id: string; question: string }
interface AskResult {
  question: string; intent: string | null; title: string; can_answer: boolean; reason: string | null; tag: string | null;
  data: unknown; answer: string[]; sources: string[]; caveats: string[]; explanation: string | null;
  mode: "demo" | "llm"; ai_error?: string | null; dataset_id: string; dataset_name: string; is_demo_data: boolean; scope: string;
  entities: Record<string, string>;
}

export default function AiAnalyst() {
  const active = useActiveDataset();
  const ds = active.data?.dataset_id;
  const opts = useFilterOptions(ds);
  const sugg = useQuery({ queryKey: ["analyst-suggestions"], queryFn: () => api<{ suggestions: Suggestion[]; mode: "demo" | "llm"; provider?: string }>("/analyst/suggestions") });
  const [question, setQuestion] = useState("");
  const [location, setLocation] = useState("");
  const [history, setHistory] = useState<AskResult[]>([]);
  const ask = useMutation({
    mutationFn: (p: { question: string; intent?: string }) => api<AskResult>("/analyst/ask", {
      method: "POST", params: { intent: p.intent }, body: { question: p.question, dataset_id: ds, location: location || null } }),
    onSuccess: (r) => { setHistory((h) => [r, ...h].slice(0, 20)); setQuestion(""); },
  });

  if (active.isLoading) return <Skeleton className="h-96" />;
  if (!active.data) return (<><PageHeader title="AI Analyst" description="Ask business questions answered from computed results." /><NoDataset /></>);
  const mode = sugg.data?.mode;
  const submit = (q: string, intent?: string) => { if (q.trim() && !ask.isPending) ask.mutate({ question: q.trim(), intent }); };

  return (
    <>
      <PageHeader title="AI Analyst" description="Ask a business question. The answer is computed by deterministic pandas analysis on the active dataset; a language model may only explain those computed numbers." />
      {mode === "demo" && (
        <div className="mb-4"><Note tone="warning"><span className="font-semibold">Demo Mode.</span> No AI API key is configured (GROQ_API_KEY in backend/.env), so answers are templated summaries of the computed results. No live language model is connected.</Note></div>
      )}
      {mode === "llm" && (
        <div className="mb-4"><Note><span className="font-semibold">Live explanations enabled.</span> Only the computed JSON result is sent to {sugg.data?.provider ?? "the language model"} for a plain-language explanation; numbers always come from the analysis.</Note></div>
      )}

      <Card>
        <p className="label">Business questions</p>
        <div className="flex flex-wrap gap-2">
          {sugg.data?.suggestions.map((s) => (
            <button key={s.id} className="chip cursor-pointer py-1 text-left hover:border-accent/50 hover:text-ink disabled:opacity-50" disabled={ask.isPending}
                    onClick={() => submit(s.question, s.id)}>
              <Sparkles className="h-3 w-3 shrink-0 text-accent-ink" aria-hidden />{s.question}
            </button>
          ))}
          {sugg.isLoading && <Skeleton className="h-7 w-full" />}
        </div>
        <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); submit(question); }}>
          <label htmlFor="q" className="sr-only">Your question</label>
          <input id="q" className="input flex-1" placeholder="e.g. Which neighborhoods have fewer listings for Thai?" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} />
          <label htmlFor="loc" className="sr-only">Location for neighborhood questions</label>
          <select id="loc" className="input sm:w-56" value={location} onChange={(e) => setLocation(e.target.value)} disabled={!opts.data?.location.length}>
            <option value="">Location (optional)</option>
            {opts.data?.location.map((l) => <option key={l.value} value={l.value}>{l.value}</option>)}
          </select>
          <button className="btn-primary" type="submit" disabled={ask.isPending || !question.trim()}>
            {ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />} Ask
          </button>
        </form>
        <p className="mt-2 text-xs text-subtle">The location selector is used for "before opening in a neighborhood" questions. Answers use the full active dataset ({ds}), not the Dashboard filters.</p>
      </Card>

      <div className="mt-6 space-y-4" aria-live="polite">
        {ask.isPending && <Card><span className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Running the analysis{mode === "llm" ? " and requesting an explanation" : ""}...</span></Card>}
        {ask.isError && <ErrorState error={ask.error} />}
        {history.length === 0 && !ask.isPending && <div className="card"><EmptyState icon={<Bot className="h-5 w-5" aria-hidden />} title="No questions yet" message="Choose one of the business questions above or type your own." /></div>}
        {history.map((r, i) => <AnswerCard key={`${r.question}-${i}`} r={r} />)}
      </div>
      <Assumptions items={[
        "Flow: question → intent detection (keyword rules) → deterministic pandas analysis → JSON result → optional LLM explanation of that JSON.",
        "If the question does not match a supported analysis, or the dataset lacks the required columns, the analyst says so instead of guessing.",
        "The language model never sees the raw dataset and is instructed not to add numbers or causal claims.",
        "Ratings are platform scores; they do not measure demand, revenue, footfall or profit.",
      ]} />
    </>
  );
}

function AnswerCard({ r }: { r: AskResult }) {
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{r.tag && <Tag kind={r.tag} />}{r.title}</span>}
          subtitle={<>Q: {r.question}</>}
          actions={r.is_demo_data ? <SampleBadge /> : undefined}>
      {!r.can_answer ? (
        <Note tone="warning"><span className="font-semibold">This dataset cannot answer the question. </span>{r.reason}</Note>
      ) : (
        <div className="space-y-4">
          {r.explanation && (
            <div className="rounded-lg border border-accent/30 bg-accent-soft/40 p-3">
              <p className="mb-1 text-xs font-semibold text-accent-ink">AI explanation of the computed result</p>
              <p className="whitespace-pre-line text-sm text-ink">{r.explanation}</p>
            </div>
          )}
          <div>
            <p className="mb-1 text-xs font-semibold text-muted">{r.mode === "demo" ? "Demo Mode: templated answer from computed results" : "Computed answer"}</p>
            <ul className="space-y-1.5">{r.answer.map((a) => <li key={a} className="text-sm leading-relaxed text-ink">{a}</li>)}</ul>
          </div>
          {r.ai_error && <Note tone="warning">{r.ai_error}</Note>}
          <details>
            <summary className="cursor-pointer text-xs font-medium text-muted">View computed JSON</summary>
            <pre className="code mt-2 max-h-72">{JSON.stringify(r.data, null, 2)}</pre>
          </details>
          <div className="flex flex-wrap items-center gap-1 border-t border-line pt-3">
            <span className="mr-1 text-xs text-subtle">Calculations used:</span>
            {r.sources.map((s) => <ShowCalculation key={s} calcId={s} datasetId={r.dataset_id} filters={EMPTY_FILTERS} />)}
          </div>
          <p className="text-xs text-subtle">{r.scope}. {r.caveats.join(" ")}</p>
        </div>
      )}
    </Card>
  );
}

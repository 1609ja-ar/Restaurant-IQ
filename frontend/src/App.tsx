import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { useActiveDataset } from "./hooks/useDataset";
import { FilterProvider } from "./hooks/useFilters";
import Dashboard from "./pages/Dashboard";
import DataPage from "./pages/Data";
import NotFound from "./pages/NotFound";

// Heavier pages are code-split so the first load stays fast.
const Explorer = lazy(() => import("./pages/Explorer"));
const MarketAnalysis = lazy(() => import("./pages/MarketAnalysis"));
const Compare = lazy(() => import("./pages/Compare"));
const SqlPlayground = lazy(() => import("./pages/SqlPlayground"));
const AiAnalyst = lazy(() => import("./pages/AiAnalyst"));
const Reports = lazy(() => import("./pages/Reports"));
const Methodology = lazy(() => import("./pages/Methodology"));
const SettingsPage = lazy(() => import("./pages/Settings"));

export default function App() {
  const active = useActiveDataset();
  return (
    <FilterProvider datasetId={active.data?.dataset_id}>
      <Layout>
        <Suspense fallback={<div className="py-10"><Spinner label="Loading page" /></div>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/explorer" element={<Explorer />} />
            <Route path="/market" element={<MarketAnalysis />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/sql" element={<SqlPlayground />} />
            <Route path="/analyst" element={<AiAnalyst />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </Layout>
    </FilterProvider>
  );
}

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { api } from "./api/client";
import { AppShell } from "./layout/AppShell";
import { Toaster } from "./components/ui";
import { CurrentRunProvider } from "./store/currentRun";
import { ConsolePage } from "./pages/ConsolePage";
import { CreatePage } from "./pages/CreatePage";
import { HistoryPage } from "./pages/HistoryPage";
import { NodeConfigPage } from "./pages/NodeConfigPage";
import { ReportPage } from "./pages/ReportPage";

function HomeRedirect(): ReactNode {
  const [target, setTarget] = useState<string | null>(null);
  useEffect(() => {
    api
      .listRuns()
      .then((runs) => setTarget(runs[0] ? `/console/${runs[0].thread_id}` : "/new"))
      .catch(() => setTarget("/new"));
  }, []);
  if (!target) {
    return (
      <div className="boot">
        <span className="boot__dot" />
        正在连接 MARS-Graph…
      </div>
    );
  }
  return <Navigate to={target} replace />;
}

function NotFound(): ReactNode {
  const navigate = useNavigate();
  return (
    <div className="boot">
      <p>页面不存在</p>
      <button type="button" className="btn btn--primary" onClick={() => navigate("/")}>
        返回工作台
      </button>
    </div>
  );
}

export function App(): ReactNode {
  return (
    <BrowserRouter>
      <CurrentRunProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="/new" element={<CreatePage />} />
            <Route path="/console/:runId" element={<ConsolePage />} />
            <Route path="/report/:runId" element={<ReportPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings/nodes" element={<NodeConfigPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppShell>
        <Toaster />
      </CurrentRunProvider>
    </BrowserRouter>
  );
}

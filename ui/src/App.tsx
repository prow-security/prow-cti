import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ProwAI } from "./components/ProwAI";
import { Sidebar } from "./components/Sidebar";
import { ComingSoonPage } from "./pages/ComingSoon";
import { IndicatorsPage } from "./pages/Indicators";
import { OverviewPage } from "./pages/Overview";
import { VulnerabilitiesPage } from "./pages/Vulnerabilities";
import type { AppPage } from "./page";

import "./styles/variables.css";
import "./styles/reset.css";
import "./styles/layout.css";
import "./styles/sidebar.css";
import "./styles/dashboard.css";
import "./styles/ai-panel.css";
import "./styles/table.css";
import "./styles/detail.css";
import "./styles/components.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function renderPage(page: AppPage) {
  switch (page) {
    case "overview":
      return <OverviewPage />;
    case "indicators":
      return <IndicatorsPage />;
    case "vulnerabilities":
      return <VulnerabilitiesPage />;
    case "relationships":
      return <ComingSoonPage label="Relationships" icon="relationships" />;
    case "threatActors":
      return <ComingSoonPage label="Threat Actors" icon="threatActors" />;
    case "connectors":
      return <ComingSoonPage label="Connectors" icon="connectors" />;
    case "audit":
      return <ComingSoonPage label="Audit Log" icon="audit" />;
    case "settings":
      return <ComingSoonPage label="Settings" icon="settings" />;
    default:
      return <OverviewPage />;
  }
}

export default function App() {
  const [page, setPage] = useState<AppPage>("overview");

  return (
    <QueryClientProvider client={queryClient}>
      <div className="app">
        <Sidebar active={page} onNavigate={setPage} />
        <div className="main-scroll">
          <main className="main">{renderPage(page)}</main>
        </div>
        <ProwAI />
      </div>
    </QueryClientProvider>
  );
}

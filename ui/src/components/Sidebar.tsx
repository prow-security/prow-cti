import type { AppPage } from "../page";
import { NavIcon } from "./NavIcons";

export interface SidebarProps {
  active: AppPage;
  onNavigate: (page: AppPage) => void;
}

const NAV: { page: AppPage; label: string; icon: string }[] = [
  { page: "overview", label: "Overview", icon: "overview" },
  { page: "indicators", label: "Indicators", icon: "indicators" },
  { page: "vulnerabilities", label: "Vulnerabilities", icon: "vulnerabilities" },
  { page: "relationships", label: "Relationships", icon: "relationships" },
  { page: "threatActors", label: "Threat Actors", icon: "threatActors" },
  { page: "connectors", label: "Connectors", icon: "connectors" },
  { page: "audit", label: "Audit Log", icon: "audit" },
  { page: "settings", label: "Settings", icon: "settings" },
];

function SourceRow({
  label,
  color,
  connected,
}: {
  label: string;
  color: string;
  connected: boolean;
}) {
  return (
    <div className="sidebar-source">
      <span className="sidebar-source__icon" style={{ background: color }} />
      <span className="sidebar-source__name">{label}</span>
      <span className={`sidebar-source__dot${connected ? " sidebar-source__dot--on" : ""}`} title={connected ? "Running" : "Not connected"} />
    </div>
  );
}

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">prow</div>
      <nav className="sidebar__nav" aria-label="Primary">
        {NAV.map((item) => {
          const isActive = active === item.page;
          return (
            <button
              key={item.page}
              type="button"
              className={`sidebar-nav-item${isActive ? " sidebar-nav-item--active" : ""}`}
              onClick={() => onNavigate(item.page)}
            >
              <span className="sidebar-nav-item__icon" aria-hidden>
                <NavIcon name={item.icon} />
              </span>
              <span className="sidebar-nav-item__label">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar__sources">
        <div className="sidebar__sources-title">Connected Sources</div>
        <SourceRow label="CISA KEV" color="#3b82f6" connected />
        <SourceRow label="MITRE ATT&CK" color="#8b5cf6" connected />
        <SourceRow label="abuse.ch URLhaus" color="#f59e0b" connected={false} />
        <SourceRow label="MISP" color="#64748b" connected={false} />
      </div>
    </aside>
  );
}

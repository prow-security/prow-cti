import { NavIcon } from "../components/NavIcons";

export function ComingSoonPage({ label, icon }: { label: string; icon: string }) {
  return (
    <div className="coming-soon">
      <div className="coming-soon__icon" aria-hidden>
        <NavIcon name={icon} />
      </div>
      <div className="coming-soon__title">{label}</div>
      <p className="coming-soon__muted">Coming in v0.2</p>
    </div>
  );
}

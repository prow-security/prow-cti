export function TypeIcon({ stixType }: { stixType: string }) {
  if (stixType === "vulnerability") {
    return (
      <span className="type-icon" aria-hidden title="Vulnerability">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 9v4M12 17h.01M10.29 3.86 1 12a9 9 0 1 0 10.42 0l-1-8.14A2 2 0 0 0 10.5 3h-1a2 2 0 0 0-1.93 1.86z" />
        </svg>
      </span>
    );
  }
  if (stixType === "relationship") {
    return (
      <span className="type-icon" aria-hidden title="Relationship">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      </span>
    );
  }
  return (
    <span className="type-icon" aria-hidden title="Indicator">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    </span>
  );
}

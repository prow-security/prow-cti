import type { ReactNode } from "react";

/** Reserved for status chips in browse and connector views. */
export function StatusBadge({ children }: { children: ReactNode }) {
  return <span className="status-badge">{children}</span>;
}

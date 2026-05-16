import { useQuery } from "@tanstack/react-query";
import { getHealth } from "../api/client";

export function HealthDot() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  if (isPending) {
    return (
      <span
        className="health-dot health-dot--loading"
        title="Checking API health"
        role="status"
        aria-label="Checking API health"
      />
    );
  }

  if (isError || !data) {
    return (
      <span
        className="health-dot health-dot--degraded"
        title="API degraded"
        role="status"
        aria-label="API degraded"
      />
    );
  }

  const ok = data.status === "ok";
  const title = ok ? "API healthy" : "API degraded";
  const className = ok ? "health-dot health-dot--ok" : "health-dot health-dot--degraded";

  return <span className={className} title={title} role="status" aria-label={title} />;
}

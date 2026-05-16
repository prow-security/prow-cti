export type SparkTrend = "up" | "flat" | "down";

export function genSparkData(points: number, trend: SparkTrend): { v: number }[] {
  return Array.from({ length: points }, (_, i) => ({
    v:
      trend === "up"
        ? 50 + i * 3 + Math.random() * 10
        : trend === "flat"
          ? 60 + Math.random() * 10
          : 100 - i * 3 + Math.random() * 10,
  }));
}

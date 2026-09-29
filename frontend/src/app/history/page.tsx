"use client";

import { useEffect, useMemo, useState } from "react";
import { History as HistoryIcon } from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getHistoryBuckets } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import type {
  HistoryBucket,
  HistoryBucketSize,
  HistoryMetric,
} from "../../types/monitoring";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

const RANGES = ["1h", "6h", "24h", "7d", "31d"] as const;
type Range = (typeof RANGES)[number];

const RANGE_MS: Record<Range, number> = {
  "1h": 3600_000,
  "6h": 6 * 3600_000,
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
  "31d": 31 * 24 * 3600_000,
};

const AUTO_BUCKET: Record<Range, HistoryBucketSize> = {
  "1h": "1m",
  "6h": "5m",
  "24h": "15m",
  "7d": "1h",
  "31d": "1d",
};

const BUCKETS: HistoryBucketSize[] = ["1m", "5m", "15m", "1h", "1d"];

const METRICS: HistoryMetric[] = [
  "voltage",
  "current",
  "active_power",
  "apparent_power",
  "power_factor",
  "frequency",
  "temperature",
];

const METRIC_UNITS: Record<HistoryMetric, string> = {
  voltage: "V",
  current: "A",
  active_power: "kW",
  apparent_power: "kVA",
  power_factor: "",
  temperature: "°C",
  frequency: "Hz",
};

function metricLabel(metric: HistoryMetric, t: Record<string, string>): string {
  const map: Record<HistoryMetric, string> = {
    voltage: t.voltage,
    current: t.current,
    active_power: t.activePower,
    apparent_power: t.apparentPower,
    power_factor: t.powerFactor,
    frequency: t.frequency,
    temperature: t.temperature,
  };
  return map[metric];
}

type ChartPoint = {
  t: string;
  label: string;
  min: number;
  max: number;
  avg: number;
  count: number;
  range: [number, number];
};

export default function HistoryPage() {
  const { t, preferences } = usePreferences();

  const [metric, setMetric] = useState<HistoryMetric>("active_power");
  const [range, setRange] = useState<Range>(
    (preferences.defaultRange as Range) ?? "24h"
  );
  const [bucket, setBucket] = useState<HistoryBucketSize>(
    AUTO_BUCKET[(preferences.defaultRange as Range) ?? "24h"]
  );
  const [buckets, setBuckets] = useState<HistoryBucket[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Trocar o período sugere a agregação automática (o usuário pode mudar
  // depois no seletor de agregação).
  function handleRangeChange(next: Range) {
    setRange(next);
    setBucket(AUTO_BUCKET[next]);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const to = new Date();
        const from = new Date(to.getTime() - RANGE_MS[range]);
        const data = await getHistoryBuckets({
          metric,
          from: from.toISOString(),
          to: to.toISOString(),
          bucket,
        });
        if (!cancelled) {
          setBuckets(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t.common.connectionError
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [metric, range, bucket, t]);

  const points: ChartPoint[] = useMemo(
    () =>
      (buckets ?? []).map((b) => ({
        t: b.t,
        label:
          range === "7d" || range === "31d"
            ? new Date(b.t).toLocaleDateString("pt-BR", {
                day: "2-digit",
                month: "2-digit",
              })
            : new Date(b.t).toLocaleTimeString("pt-BR", {
                hour: "2-digit",
                minute: "2-digit",
              }),
        min: b.min,
        max: b.max,
        avg: b.avg,
        count: b.count,
        range: [b.min, b.max],
      })),
    [buckets, range]
  );

  const unit = METRIC_UNITS[metric];

  return (
    <div className="space-y-5">
      <PageHeader title={t.history.title} subtitle={t.history.subtitle} />

      <Card>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.history.metric}
            </span>
            <select
              className="field"
              value={metric}
              onChange={(e) => setMetric(e.target.value as HistoryMetric)}
            >
              {METRICS.map((m) => (
                <option key={m} value={m}>
                  {metricLabel(m, t.dashboard)}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.history.range}
            </span>
            <select
              className="field"
              value={range}
              onChange={(e) => handleRangeChange(e.target.value as Range)}
            >
              {RANGES.map((r) => (
                <option key={r} value={r}>
                  {t.history.ranges[r]}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.history.bucket}
            </span>
            <select
              className="field"
              value={bucket}
              onChange={(e) => setBucket(e.target.value as HistoryBucketSize)}
            >
              {BUCKETS.map((b) => (
                <option key={b} value={b}>
                  {t.history.buckets[b]}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      {error && <ErrorBanner message={error} />}

      <Card>
        <CardHeader
          eyebrow={t.history.title}
          title={`${metricLabel(metric, t.dashboard)}${unit ? ` (${unit})` : ""}`}
        />
        <div className="mt-4 h-[320px] w-full">
          {loading ? (
            <LoadingState />
          ) : points.length === 0 ? (
            <EmptyState
              icon={HistoryIcon}
              title={t.common.noData}
              message={t.history.noBuckets}
            />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={points}
                margin={{ top: 10, right: 5, left: -10, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="var(--border)"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "var(--faint)", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={40}
                />
                <YAxis
                  tick={{ fill: "var(--faint)", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  domain={["auto", "auto"]}
                  tickFormatter={(v: number) => formatNumber(v, 1)}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "10px",
                    color: "var(--text)",
                  }}
                  labelStyle={{ color: "var(--muted)", marginBottom: 4 }}
                  formatter={(value, name) => {
                    const labels: Record<string, string> = {
                      avg: t.dashboard.avg,
                      min: t.dashboard.min,
                      max: t.dashboard.max,
                    };
                    if (name === "count") {
                      return [
                        t.history.readingsInBucket.replace(
                          "{n}",
                          String(value)
                        ),
                        "",
                      ];
                    }
                    return [
                      `${formatNumber(Number(value), 2)}${unit ? ` ${unit}` : ""}`,
                      labels[String(name)] ?? name,
                    ];
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="range"
                  stroke="none"
                  fill="var(--info)"
                  fillOpacity={0.18}
                  name="min-max"
                />
                <Line
                  type="monotone"
                  dataKey="avg"
                  stroke="var(--info)"
                  strokeWidth={2}
                  dot={false}
                  name="avg"
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </Card>
    </div>
  );
}

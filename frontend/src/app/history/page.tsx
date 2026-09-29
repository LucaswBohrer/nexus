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

import { getHistoryBuckets, getHistoryExtremes } from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import type {
  HistoryBucket,
  HistoryBucketSize,
  HistoryExtremesResponse,
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
type PresetRange = (typeof RANGES)[number];
type Range = PresetRange | "custom";

const RANGE_MS: Record<PresetRange, number> = {
  "1h": 3600_000,
  "6h": 6 * 3600_000,
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
  "31d": 31 * 24 * 3600_000,
};

const AUTO_BUCKET: Record<PresetRange, HistoryBucketSize> = {
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

/** Limites do período; null = personalizado ainda não preenchido/válido. */
function resolveBounds(
  range: Range,
  customFrom: string,
  customTo: string
): { from: Date; to: Date } | null {
  if (range === "custom") {
    if (!customFrom || !customTo) {
      return null;
    }
    const from = new Date(customFrom);
    const to = new Date(customTo);
    if (
      Number.isNaN(from.getTime()) ||
      Number.isNaN(to.getTime()) ||
      from >= to
    ) {
      return null;
    }
    return { from, to };
  }
  const to = new Date();
  return { from: new Date(to.getTime() - RANGE_MS[range]), to };
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
    AUTO_BUCKET[(preferences.defaultRange as PresetRange) ?? "24h"]
  );
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [buckets, setBuckets] = useState<HistoryBucket[] | null>(null);
  const [extremes, setExtremes] =
    useState<HistoryExtremesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Trocar o período sugere a agregação automática (o usuário pode mudar
  // depois no seletor de agregação).
  function handleRangeChange(next: Range) {
    setRange(next);
    if (next !== "custom") {
      setBucket(AUTO_BUCKET[next]);
    }
  }

  // Limites do período atual; null = personalizado ainda não preenchido.
  const bounds = resolveBounds(range, customFrom, customTo);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const b = resolveBounds(range, customFrom, customTo);
      if (!b) {
        if (!cancelled) {
          setBuckets([]);
          setExtremes(null);
          setError(null);
          setLoading(false);
        }
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const [bucketData, extremesData] = await Promise.all([
          getHistoryBuckets({
            metric,
            from: b.from.toISOString(),
            to: b.to.toISOString(),
            bucket,
          }),
          getHistoryExtremes({
            metric,
            from: b.from.toISOString(),
            to: b.to.toISOString(),
          }),
        ]);
        if (!cancelled) {
          setBuckets(bucketData);
          setExtremes(extremesData);
        }
      } catch (err) {
        if (!cancelled) {
          // Mensagens 422 do backend (ex.: período > 31 dias, buckets >
          // 2000) chegam aqui com o detalhe original — exibidas como são.
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
  }, [metric, range, bucket, customFrom, customTo, t]);

  const points: ChartPoint[] = useMemo(() => {
    const spanMs =
      bounds !== null ? bounds.to.getTime() - bounds.from.getTime() : 0;
    const showDate = spanMs > 2 * 24 * 3600_000;
    return (buckets ?? []).map((b) => ({
      t: b.t,
      label: showDate
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
    }));
  }, [buckets, bounds]);

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
              <option value="custom">{t.history.customRange}</option>
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
      {range === "custom" && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.common.from}
            </span>
            <input
              type="datetime-local"
              className="field"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.common.to}
            </span>
            <input
              type="datetime-local"
              className="field"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
            />
          </label>
        </div>
      )}
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

      <Card>
        <CardHeader
          eyebrow={t.history.extremes}
          title={`${metricLabel(metric, t.dashboard)}${unit ? ` (${unit})` : ""} — ${t.history.extremes}`}
        />
        {loading ? (
          <LoadingState />
        ) : extremes && extremes.count > 0 ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl bg-surface-2 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-faint">
                {t.history.extremesMin}
              </p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">
                {extremes.min
                  ? formatNumber(extremes.min.value, 2)
                  : "--"}
                {unit && (
                  <span className="text-sm font-normal text-faint">
                    {" "}
                    {unit}
                  </span>
                )}
              </p>
              {extremes.min && (
                <p className="mt-1 text-xs text-faint">
                  {t.history.recordedAt}{" "}
                  {formatDateTime(extremes.min.timestamp, preferences)}
                </p>
              )}
            </div>
            <div className="rounded-xl bg-surface-2 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-faint">
                {t.history.extremesMax}
              </p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">
                {extremes.max
                  ? formatNumber(extremes.max.value, 2)
                  : "--"}
                {unit && (
                  <span className="text-sm font-normal text-faint">
                    {" "}
                    {unit}
                  </span>
                )}
              </p>
              {extremes.max && (
                <p className="mt-1 text-xs text-faint">
                  {t.history.recordedAt}{" "}
                  {formatDateTime(extremes.max.timestamp, preferences)}
                </p>
              )}
            </div>
            <div className="rounded-xl bg-surface-2 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-faint">
                {t.history.extremesAvg}
              </p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">
                {extremes.avg !== null
                  ? formatNumber(extremes.avg, 2)
                  : "--"}
                {unit && (
                  <span className="text-sm font-normal text-faint">
                    {" "}
                    {unit}
                  </span>
                )}
              </p>
            </div>
            <div className="rounded-xl bg-surface-2 px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-faint">
                {t.analytics.readings}
              </p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-ink">
                {formatNumber(extremes.count, 0)}
              </p>
            </div>
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-faint">
            {t.history.noBuckets}
          </p>
        )}
      </Card>
    </div>
  );
}

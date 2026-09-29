"use client";

import Link from "next/link";
import { useMemo } from "react";
import type { ElementType } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Gauge,
  Thermometer,
  TriangleAlert,
  Zap,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getDiagnostics,
  getEventsV1,
  getHistoryBuckets,
  getStatsSummary,
} from "../lib/api";
import {
  formatNumber,
  formatRelative,
  formatUptime,
} from "../lib/format";
import { usePreferences } from "../lib/preferences";
import { useNow, usePoll } from "../lib/usePoll";
import type {
  HistoryBucket,
  HistoryMetric,
  StatsSummary,
  V1Event,
} from "../types/monitoring";
import {
  Badge,
  Card,
  CardHeader,
  ErrorBanner,
  LoadingState,
} from "../components/ui";

type MetricKey =
  | "voltage"
  | "current"
  | "active_power"
  | "apparent_power"
  | "temperature"
  | "energy_today";

interface MetricDef {
  key: MetricKey;
  label: string;
  unit: string;
  digits: number;
  icon: ElementType;
  sparkMetric?: HistoryMetric;
  getValue: (summary: StatsSummary) => number | null;
  getRange?: (summary: StatsSummary) => { min: number; max: number } | null;
}

function metricDefs(t: {
  voltage: string;
  current: string;
  activePower: string;
  apparentPower: string;
  temperature: string;
  energyToday: string;
}): MetricDef[] {
  return [
    {
      key: "voltage",
      label: t.voltage,
      unit: "V",
      digits: 1,
      icon: Gauge,
      sparkMetric: "voltage",
      getValue: (s) => s.current.voltage,
      getRange: (s) => s.last_24h.voltage ?? null,
    },
    {
      key: "current",
      label: t.current,
      unit: "A",
      digits: 1,
      icon: Activity,
      sparkMetric: "current",
      getValue: (s) => s.current.current,
      getRange: (s) => s.last_24h.current ?? null,
    },
    {
      key: "active_power",
      label: t.activePower,
      unit: "kW",
      digits: 2,
      icon: Zap,
      sparkMetric: "active_power",
      getValue: (s) => s.current.active_power,
      getRange: (s) => s.last_24h.active_power ?? null,
    },
    {
      key: "apparent_power",
      label: t.apparentPower,
      unit: "kVA",
      digits: 2,
      icon: Zap,
      sparkMetric: "apparent_power",
      // Aritmética sobre leituras reais (V*I/1000) — não é regra de negócio.
      getValue: (s) => (s.current.voltage * s.current.current) / 1000,
    },
    {
      key: "temperature",
      label: t.temperature,
      unit: "°C",
      digits: 1,
      icon: Thermometer,
      sparkMetric: "temperature",
      getValue: (s) => s.current.temperature,
      getRange: (s) => s.last_24h.temperature ?? null,
    },
    {
      key: "energy_today",
      label: t.energyToday,
      unit: "kWh",
      digits: 2,
      icon: Cpu,
      getValue: (s) => s.energy_today_kwh,
    },
  ];
}

function Sparkline({ buckets }: { buckets: HistoryBucket[] }) {
  const data = useMemo(
    () => buckets.map((b, i) => ({ i, v: b.avg })),
    [buckets]
  );
  if (data.length < 2) {
    return null;
  }
  return (
    <div className="mt-3 h-10 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <Line
            type="monotone"
            dataKey="v"
            stroke="var(--info)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function MetricCard({
  def,
  summary,
  spark,
}: {
  def: MetricDef;
  summary: StatsSummary;
  spark: HistoryBucket[];
}) {
  const Icon = def.icon;
  const value = def.getValue(summary);
  const range = def.getRange?.(summary) ?? null;
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-3 text-muted">
          <Icon size={20} />
        </div>
      </div>
      <div className="mt-4">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-faint">
          {def.label}
        </p>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-semibold tracking-tight text-ink">
            {formatNumber(value, def.digits)}
          </span>
          <span className="text-sm text-faint">{def.unit}</span>
        </div>
        {range && (
          <p className="mt-1 text-[11px] text-faint">
            24h: {formatNumber(range.min, def.digits)} –{" "}
            {formatNumber(range.max, def.digits)} {def.unit}
          </p>
        )}
        {def.sparkMetric && <Sparkline buckets={spark} />}
      </div>
    </Card>
  );
}

async function fetchActiveEvents(): Promise<V1Event[]> {
  const [open, acknowledged] = await Promise.all([
    getEventsV1({ status: "open", limit: 5 }),
    getEventsV1({ status: "acknowledged", limit: 5 }),
  ]);
  return [...open.events, ...acknowledged.events]
    .sort((a, b) => b.id - a.id)
    .slice(0, 5);
}

async function fetchSparklines(): Promise<Record<string, HistoryBucket[]>> {
  const to = new Date();
  const from = new Date(to.getTime() - 3 * 3600_000);
  const metrics: HistoryMetric[] = [
    "voltage",
    "current",
    "active_power",
    "apparent_power",
    "temperature",
  ];
  const entries = await Promise.all(
    metrics.map(async (metric) => {
      try {
        const buckets = await getHistoryBuckets({
          metric,
          from: from.toISOString(),
          to: to.toISOString(),
          bucket: "5m",
        });
        return [metric, buckets] as const;
      } catch {
        return [metric, []] as const;
      }
    })
  );
  return Object.fromEntries(entries);
}

export default function DashboardPage() {
  const { t, preferences } = usePreferences();
  useNow(5000);

  const pollMs = preferences.pollingIntervalMs;

  const summaryPoll = usePoll(getStatsSummary, pollMs, t.common.connectionError);
  const diagPoll = usePoll(getDiagnostics, pollMs, t.common.connectionError);
  const eventsPoll = usePoll(fetchActiveEvents, pollMs, t.common.connectionError);
  const sparkPoll = usePoll(fetchSparklines, 60000, t.common.connectionError);
  const trendPoll = usePoll(
    () =>
      getHistoryBuckets({
        metric: "active_power",
        from: new Date(Date.now() - 3 * 3600_000).toISOString(),
        to: new Date().toISOString(),
        bucket: "5m",
      }),
    60000,
    t.common.connectionError
  );

  const defs = useMemo(() => metricDefs(t.dashboard), [t]);
  const visibleDefs = useMemo(() => {
    const favs = preferences.favoriteMetrics;
    if (!favs || favs.length === 0) {
      return defs;
    }
    return defs.filter((d) => favs.includes(d.key));
  }, [defs, preferences.favoriteMetrics]);

  const summary = summaryPoll.data;
  const diagnosis = diagPoll.data?.diagnosis;
  const reading = diagPoll.data?.reading ?? summary?.current ?? null;
  const events = eventsPoll.data ?? [];
  const trend = useMemo(
    () => trendPoll.data ?? [],
    [trendPoll.data]
  );

  const error =
    summaryPoll.error ?? diagPoll.error ?? eventsPoll.error ?? null;
  const loading =
    (summaryPoll.loading || diagPoll.loading) && !summary && !diagnosis;

  // Comparação hora atual vs. hora anterior — calculada de verdade a
  // partir dos buckets (12 buckets de 5 min = 1 h). Só exibe se houver
  // dados suficientes nos dois períodos.
  const hourComparison = useMemo(() => {
    const valid = trend.filter((b) => b.count > 0);
    if (valid.length < 18) {
      return null;
    }
    const prev = valid.slice(-24, -12);
    const curr = valid.slice(-12);
    if (prev.length < 6 || curr.length < 6) {
      return null;
    }
    const avg = (xs: HistoryBucket[]) =>
      xs.reduce((acc, b) => acc + b.avg, 0) / xs.length;
    const prevAvg = avg(prev);
    const currAvg = avg(curr);
    if (prevAvg === 0) {
      return null;
    }
    return ((currAvg - prevAvg) / prevAvg) * 100;
  }, [trend]);

  const status = diagnosis?.status ?? "normal";
  const uptimeTemplates = {
    full: t.time.uptimeFormat,
    short: t.time.uptimeShort,
    minutes: t.time.uptimeMinutes,
  };

  return (
    <div className="space-y-5">
      {error && (
        <ErrorBanner
          message={error}
          onRetry={() => {
            summaryPoll.refresh();
            diagPoll.refresh();
            eventsPoll.refresh();
          }}
        />
      )}

      {loading ? (
        <LoadingState />
      ) : (
        <>
          {/* STATUS GERAL */}
          <div className="flex flex-wrap items-center gap-3">
            <Badge
              tone={status}
              icon={status === "normal" ? CheckCircle2 : TriangleAlert}
            >
              {t.dashboard.overallStatus}:{" "}
              {t.status[status as "normal" | "warning" | "critical"]}
            </Badge>
            {reading && (
              <span className="text-xs text-faint">
                {t.common.lastUpdate}:{" "}
                {formatRelative(reading.timestamp, t.time.justNow, {
                  secondsAgo: t.time.secondsAgo,
                  minutesAgo: t.time.minutesAgo,
                  hoursAgo: t.time.hoursAgo,
                  daysAgo: t.time.daysAgo,
                })}
              </span>
            )}
            {summary && (
              <span className="text-xs text-faint">
                {t.dashboard.uptime}:{" "}
                {formatUptime(summary.uptime_s, uptimeTemplates)}
              </span>
            )}
          </div>

          {/* DIAGNÓSTICO REAL */}
          {diagnosis && diagnosis.anomalies.length > 0 && (
            <Card>
              <CardHeader
                eyebrow={t.dashboard.diagnosis}
                title={t.dashboard.diagnosis}
                action={
                  <Badge tone={diagnosis.severity}>
                    {t.status[diagnosis.severity]}
                  </Badge>
                }
              />
              <div className="mt-4 space-y-2">
                {diagnosis.anomalies.map((anomaly) => (
                  <div
                    key={anomaly}
                    className="flex items-center gap-2 rounded-xl bg-surface-2 px-4 py-2.5 text-sm text-ink"
                  >
                    <TriangleAlert
                      size={15}
                      className="shrink-0 text-[var(--warn)]"
                    />
                    {anomaly}
                  </div>
                ))}
                {diagnosis.recommendations.length > 0 && (
                  <div className="pt-1">
                    <p className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">
                      {t.dashboard.recommendations}
                    </p>
                    {diagnosis.recommendations.map((rec, i) => (
                      <p key={i} className="text-sm text-muted">
                        • {rec}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* MÉTRICAS */}
          {summary && (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {visibleDefs.map((def) => (
                <MetricCard
                  key={def.key}
                  def={def}
                  summary={summary}
                  spark={
                    def.sparkMetric
                      ? (sparkPoll.data?.[def.sparkMetric] ?? [])
                      : []
                  }
                />
              ))}
            </div>
          )}

          {/* TENDÊNCIA AGREGADA */}
          <Card>
            <CardHeader
              eyebrow={t.dashboard.powerTrend}
              title={`${t.dashboard.activePower} — 3h`}
              action={
                hourComparison !== null ? (
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-medium ${
                      hourComparison >= 0
                        ? "badge-amber"
                        : "badge-green"
                    }`}
                  >
                    {hourComparison >= 0
                      ? t.dashboard.increase.replace(
                          "{n}",
                          formatNumber(hourComparison, 1)
                        )
                      : t.dashboard.decrease.replace(
                          "{n}",
                          formatNumber(Math.abs(hourComparison), 1)
                        )}
                  </span>
                ) : undefined
              }
            />
            <div className="mt-4 h-[260px] w-full">
              {trend.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={trend.map((b) => ({
                      label: new Date(b.t).toLocaleTimeString("pt-BR", {
                        hour: "2-digit",
                        minute: "2-digit",
                      }),
                      avg: b.avg,
                      range: [b.min, b.max],
                    }))}
                    margin={{ top: 10, right: 5, left: -15, bottom: 0 }}
                  >
                    <CartesianGrid stroke="var(--border)" vertical={false} />
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
                      formatter={(value, name) => [
                        `${formatNumber(Number(value), 2)} kW`,
                        name === "avg" ? t.dashboard.avg : t.dashboard.max,
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="range"
                      stroke="none"
                      fill="var(--info)"
                      fillOpacity={0.15}
                      name="range"
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
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-faint">
                  {t.common.waitingData}
                </div>
              )}
            </div>
          </Card>

          {/* EVENTOS ATIVOS + CONTAGENS */}
          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader
                eyebrow={t.dashboard.activeEvents}
                title={t.dashboard.activeEvents}
                action={
                  <Link
                    href="/events"
                    className="flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-xs font-medium text-[var(--info)]"
                  >
                    {t.common.viewAll}
                    <ArrowRight size={14} />
                  </Link>
                }
              />
              <div className="mt-4 space-y-2">
                {events.length === 0 ? (
                  <p className="py-4 text-center text-sm text-faint">
                    {t.dashboard.noActiveEvents}
                  </p>
                ) : (
                  events.map((event) => (
                    <Link
                      key={event.id}
                      href="/events"
                      className="flex items-center gap-3 rounded-xl bg-surface-2 px-4 py-3"
                    >
                      <TriangleAlert
                        size={16}
                        className={`shrink-0 ${
                          event.severity === "critical"
                            ? "text-[var(--bad)]"
                            : "text-[var(--warn)]"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          {event.event_type}
                        </p>
                        <p className="truncate text-xs text-muted">
                          {event.message}
                        </p>
                      </div>
                      <span className="shrink-0 text-[11px] text-faint">
                        ×{event.occurrences}
                      </span>
                    </Link>
                  ))
                )}
              </div>
            </Card>

            <Card>
              <CardHeader
                eyebrow={t.dashboard.last24h}
                title={t.dashboard.last24h}
                action={
                  <Link
                    href="/analytics"
                    className="flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-xs font-medium text-[var(--info)]"
                  >
                    {t.dashboard.viewAnalytics}
                    <ArrowRight size={14} />
                  </Link>
                }
              />
              {summary && (
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-xl bg-surface-2 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wider text-faint">
                      {t.dashboard.storedReadings}
                    </p>
                    <p className="mt-1 text-lg font-semibold text-ink">
                      {formatNumber(summary.readings_count, 0)}
                    </p>
                  </div>
                  <div className="rounded-xl bg-surface-2 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wider text-faint">
                      {t.dashboard.energyToday}
                    </p>
                    <p className="mt-1 text-lg font-semibold text-ink">
                      {formatNumber(summary.energy_today_kwh, 2)}{" "}
                      <span className="text-xs font-normal text-faint">
                        kWh
                      </span>
                    </p>
                  </div>
                  {Object.entries(summary.status_counts_24h).map(
                    ([statusKey, count]) => (
                      <div
                        key={statusKey}
                        className="rounded-xl bg-surface-2 px-4 py-3"
                      >
                        <p className="text-[11px] uppercase tracking-wider text-faint">
                          {t.status[statusKey as "normal" | "warning" | "critical"] ??
                            statusKey}
                        </p>
                        <p className="mt-1 text-lg font-semibold text-ink">
                          {formatNumber(count, 0)}
                        </p>
                      </div>
                    )
                  )}
                </div>
              )}
            </Card>
          </div>

          {diagnosis && diagnosis.anomalies.length === 0 && (
            <Card>
              <div className="flex items-center gap-3">
                <CheckCircle2
                  size={20}
                  className="shrink-0 text-[var(--ok)]"
                />
                <p className="text-sm text-muted">
                  {t.dashboard.noAnomalies}
                </p>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

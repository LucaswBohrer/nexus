"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  CalendarRange,
  PlugZap,
  Stethoscope,
} from "lucide-react";

import { getAnalyticsOverview } from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { useEquipment } from "../../lib/equipment";
import { usePreferences } from "../../lib/preferences";
import type { AnalyticsOverview } from "../../types/monitoring";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";
import { EquipmentContextLine } from "../../components/EquipmentContext";

const PERIODS = ["24h", "7d", "31d"] as const;
type Period = (typeof PERIODS)[number];

const PERIOD_MS: Record<Period, number> = {
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
  "31d": 31 * 24 * 3600_000,
};

const METRIC_UNITS: Record<string, string> = {
  voltage: "V",
  current: "A",
  active_power: "kW",
  apparent_power: "kVA",
  power_factor: "",
  frequency: "Hz",
  temperature: "°C",
};

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-surface-3 text-muted">
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-faint">
            {label}
          </p>
          <p className="mt-1 truncate text-2xl font-semibold tracking-tight text-ink">
            {value}
          </p>
          {hint && <p className="mt-0.5 text-xs text-faint">{hint}</p>}
        </div>
      </div>
    </Card>
  );
}

function CountRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-muted">{label}</span>
      <span className="text-sm font-semibold text-ink">
        {formatNumber(value, 0)}
      </span>
    </div>
  );
}

export default function AnalyticsPage() {
  const { t, preferences } = usePreferences();
  const { equipmentId } = useEquipment();
  const [period, setPeriod] = useState<Period>("24h");
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const to = new Date();
        const from = new Date(to.getTime() - PERIOD_MS[period]);
        const overview = await getAnalyticsOverview({
          from: from.toISOString(),
          to: to.toISOString(),
          equipmentId,
        });
        if (!cancelled) {
          setData(overview);
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
  }, [period, equipmentId, t]);

  const metricLabels: Record<string, string> = {
    voltage: t.dashboard.voltage,
    current: t.dashboard.current,
    active_power: t.dashboard.activePower,
    apparent_power: t.dashboard.apparentPower,
    power_factor: t.dashboard.powerFactor,
    frequency: t.dashboard.frequency,
    temperature: t.dashboard.temperature,
  };

  const severity = data?.events_by_severity ?? {};
  const status = data?.events_by_status ?? {};
  const perMetric = data ? Object.entries(data.per_metric) : [];

  return (
    <div className="space-y-5">
      <EquipmentContextLine />
      <PageHeader
        title={t.analytics.title}
        subtitle={t.analytics.subtitle}
      />

      <Card>
        <label className="block max-w-xs">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
            {t.analytics.period}
          </span>
          <select
            className="field"
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {t.analytics.periods[p]}
              </option>
            ))}
          </select>
        </label>
      </Card>

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <LoadingState />
      ) : data && data.readings_count > 0 ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              icon={PlugZap}
              label={t.analytics.energyInPeriod}
              value={`${formatNumber(data.energy_kwh, 2)} kWh`}
            />
            <StatCard
              icon={Activity}
              label={t.analytics.readings}
              value={formatNumber(data.readings_count, 0)}
            />
            <StatCard
              icon={Stethoscope}
              label={t.analytics.episodes}
              value={formatNumber(data.episodes.total, 0)}
              hint={t.analytics.openEpisodes.replace(
                "{n}",
                String(data.episodes.open)
              )}
            />
            <StatCard
              icon={CalendarRange}
              label={t.analytics.period}
              value={t.analytics.periods[period]}
              hint={`${formatDateTime(data.from, preferences)} — ${formatDateTime(data.to, preferences)}`}
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader
                eyebrow={t.analytics.eventsBySeverity}
                title={t.analytics.eventsBySeverity}
              />
              <div className="mt-2 divide-y divide-[var(--border)]">
                <CountRow
                  label={t.status.info}
                  value={severity.info ?? 0}
                />
                <CountRow
                  label={t.status.warning}
                  value={severity.warning ?? 0}
                />
                <CountRow
                  label={t.status.critical}
                  value={severity.critical ?? 0}
                />
              </div>
            </Card>

            <Card>
              <CardHeader
                eyebrow={t.analytics.eventsByStatus}
                title={t.analytics.eventsByStatus}
              />
              <div className="mt-2 divide-y divide-[var(--border)]">
                <CountRow
                  label={t.status.open}
                  value={status.open ?? 0}
                />
                <CountRow
                  label={t.status.acknowledged}
                  value={status.acknowledged ?? 0}
                />
                <CountRow
                  label={t.status.resolved}
                  value={status.resolved ?? 0}
                />
              </div>
            </Card>
          </div>

          <Card>
            <CardHeader
              eyebrow={t.analytics.perMetric}
              title={t.analytics.perMetric}
            />
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wider text-faint">
                    <th className="py-2 pr-4 font-medium">
                      {t.analytics.metric}
                    </th>
                    <th className="py-2 pr-4 text-right font-medium">
                      {t.dashboard.min}
                    </th>
                    <th className="py-2 pr-4 text-right font-medium">
                      {t.dashboard.max}
                    </th>
                    <th className="py-2 text-right font-medium">
                      {t.dashboard.avg}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {perMetric.map(([metric, agg]) => {
                    const unit = METRIC_UNITS[metric] ?? "";
                    return (
                      <tr key={metric}>
                        <td className="py-2.5 pr-4 text-muted">
                          {metricLabels[metric] ?? metric}
                          {unit ? (
                            <span className="text-faint"> ({unit})</span>
                          ) : null}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums text-ink">
                          {formatNumber(agg.min, 2)}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular-nums text-ink">
                          {formatNumber(agg.max, 2)}
                        </td>
                        <td className="py-2.5 text-right tabular-nums text-ink">
                          {formatNumber(agg.avg, 2)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <p className="text-xs text-faint">{t.analytics.note}</p>
        </>
      ) : data ? (
        <Card>
          <EmptyState
            icon={BarChart3}
            title={t.common.noData}
            message={t.analytics.emptyPeriod}
          />
        </Card>
      ) : null}
    </div>
  );
}

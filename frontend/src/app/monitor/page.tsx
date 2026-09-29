"use client";

import type { ElementType } from "react";
import {
  Activity,
  Cpu,
  Gauge,
  Thermometer,
  Timer,
  Waves,
  Zap,
} from "lucide-react";

import { getCurrentReading } from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useNow, usePoll } from "../../lib/usePoll";
import { Badge, Card, ErrorBanner, LoadingState, PageHeader } from "../../components/ui";

function LiveMetric({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: ElementType;
  label: string;
  value: string;
  unit: string;
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
            {value}{" "}
            <span className="text-sm font-normal text-faint">{unit}</span>
          </p>
        </div>
      </div>
    </Card>
  );
}

export default function MonitorPage() {
  const { t, preferences } = usePreferences();
  useNow(5000);
  const { data: reading, error, loading, refresh } = usePoll(
    getCurrentReading,
    preferences.pollingIntervalMs,
    t.common.connectionError
  );

  const status = reading?.status ?? "normal";
  const apparentPower =
    reading !== null ? (reading.voltage * reading.current) / 1000 : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.monitor.title}
        subtitle={t.monitor.subtitle}
        actions={
          <Badge
            tone={status}
            icon={Activity}
          >
            {t.status[status as "normal" | "warning" | "critical"]}
          </Badge>
        }
      />

      {error && (
        <ErrorBanner
          message={
            error === "unauthorized" ? t.common.unauthorized : error
          }
          onRetry={refresh}
        />
      )}

      {loading && !reading ? (
        <LoadingState />
      ) : reading ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <LiveMetric
              icon={Gauge}
              label={t.dashboard.voltage}
              value={formatNumber(reading.voltage, 1)}
              unit="V"
            />
            <LiveMetric
              icon={Activity}
              label={t.dashboard.current}
              value={formatNumber(reading.current, 1)}
              unit="A"
            />
            <LiveMetric
              icon={Zap}
              label={t.dashboard.activePower}
              value={formatNumber(reading.active_power, 2)}
              unit="kW"
            />
            <LiveMetric
              icon={Zap}
              label={t.dashboard.apparentPower}
              value={formatNumber(apparentPower, 2)}
              unit="kVA"
            />
            <LiveMetric
              icon={Cpu}
              label={t.dashboard.powerFactor}
              value={formatNumber(reading.power_factor, 2)}
              unit=""
            />
            <LiveMetric
              icon={Waves}
              label={t.dashboard.frequency}
              value={formatNumber(reading.frequency, 2)}
              unit="Hz"
            />
            <LiveMetric
              icon={Thermometer}
              label={t.dashboard.temperature}
              value={formatNumber(reading.temperature, 1)}
              unit="°C"
            />
            <LiveMetric
              icon={Timer}
              label={t.monitor.timestamp}
              value={formatDateTime(reading.timestamp, preferences).slice(11)}
              unit=""
            />
          </div>

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-faint">
              <span>{t.monitor.liveReading}</span>
              <span>
                {t.common.lastUpdate}:{" "}
                {formatDateTime(reading.timestamp, preferences)}
              </span>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}

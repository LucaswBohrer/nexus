"use client";

import type { ElementType } from "react";
import {
  Activity,
  Cpu,
  Gauge,
  Radio,
  Thermometer,
  Timer,
  TimerOff,
  Waves,
  Zap,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatDateTime, formatNumber, formatTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { useRealtimeReading } from "../../lib/useStream";
import {
  Badge,
  Card,
  CardHeader,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

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
  const {
    reading,
    transport,
    error,
    recent,
    loading,
  } = useRealtimeReading(preferences.pollingIntervalMs, t.common.connectionError);

  const status = reading?.status ?? "normal";
  const apparentPower =
    reading !== null ? (reading.voltage * reading.current) / 1000 : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.monitor.title}
        subtitle={t.monitor.subtitle}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              tone={transport === "sse" ? "normal" : "warning"}
              icon={transport === "sse" ? Radio : TimerOff}
            >
              {transport === "sse" ? t.monitor.realtime : t.monitor.polling}
            </Badge>
            <Badge tone={status} icon={Activity}>
              {t.status[status as "normal" | "warning" | "critical"]}
            </Badge>
          </div>
        }
      />

      {transport === "poll" && reading && (
        <p className="text-xs text-faint">{t.monitor.streamUnavailable}</p>
      )}

      {error && (
        <ErrorBanner
          message={
            error === "unauthorized" ? t.common.unauthorized : error
          }
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
              value={formatTime(reading.timestamp, preferences)}
              unit=""
            />
          </div>

          <Card>
            <CardHeader
              eyebrow={t.monitor.recentPower}
              title={`${t.monitor.recentPower} (kW)`}
            />
            <div className="mt-4 h-[220px] w-full">
              {recent.length < 2 ? (
                <div className="flex h-full items-center justify-center text-sm text-faint">
                  {t.common.waitingData}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={recent.map((p) => ({
                      label: new Date(p.t).toLocaleTimeString("pt-BR", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      }),
                      power: p.active_power,
                    }))}
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
                      minTickGap={48}
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
                      formatter={(value) => [
                        `${formatNumber(Number(value), 2)} kW`,
                        t.dashboard.activePower,
                      ]}
                    />
                    <Line
                      type="monotone"
                      dataKey="power"
                      stroke="var(--info)"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
            <p className="mt-3 text-xs text-faint">{t.monitor.streamNote}</p>
          </Card>

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

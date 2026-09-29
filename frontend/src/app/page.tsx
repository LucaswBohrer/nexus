"use client";

import { useEffect, useRef, useState, type ElementType } from "react";

import {
  getCurrentReading,
  getEvents,
  getHistory,
} from "../lib/api";

import type {
  ElectricalReading,
  MonitoringEvent,
} from "../types/monitoring";

import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  Cpu,
  Gauge,
  Radio,
  Thermometer,
  Zap,
} from "lucide-react";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type PowerHistoryPoint = {
  time: string;
  power: number;
};

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  status = "live",
}: {
  icon: ElementType;
  label: string;
  value: string;
  unit: string;
  status?: "live" | "warning";
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#111318] p-5 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#1b1e25]">
          <Icon size={20} className="text-gray-300" />
        </div>

        <span className="text-lg text-gray-500">•••</span>
      </div>

      <div className="mt-5">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
          {label}
        </p>

        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-semibold tracking-tight text-white">
            {value}
          </span>

          <span className="text-sm text-gray-500">
            {unit}
          </span>
        </div>

        <div className="mt-4 flex items-center gap-2 text-xs">
          {status === "live" ? (
            <>
              <span className="flex items-center gap-1 text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Live
              </span>

              <span className="text-gray-600">
                vs last hour
              </span>
            </>
          ) : (
            <span className="flex items-center gap-1 text-amber-400">
              <AlertTriangle size={13} />
              Warning
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function DiagnosticItem({
  label,
  value,
  unit,
  normal,
}: {
  label: string;
  value: string;
  unit: string;
  normal: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-white/5 bg-[#111318] px-4 py-3">
      <div>
        <p className="text-xs uppercase tracking-wider text-gray-500">
          {label}
        </p>

        <p className="mt-1 text-sm font-medium text-white">
          {value}{" "}
          <span className="text-gray-500">
            {unit}
          </span>
        </p>
      </div>

      {normal ? (
        <div className="flex items-center gap-1.5 text-xs text-emerald-400">
          <CheckCircle2 size={15} />
          Normal
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-xs text-amber-400">
          <AlertTriangle size={15} />
          Warning
        </div>
      )}
    </div>
  );
}

export default function Home() {
  const [reading, setReading] =
    useState<ElectricalReading | null>(null);

  const [powerHistory, setPowerHistory] =
    useState<PowerHistoryPoint[]>([]);

  const [events, setEvents] =
    useState<MonitoringEvent[]>([]);

  const [loading, setLoading] =
    useState(true);

  const initialLoadDone =
    useRef(false);

  const [error, setError] =
    useState<string | null>(null);

  async function loadReading() {
    // The first call boots the dashboard (cards show "--" placeholders);
    // every later call is a background refresh that keeps the last valid
    // values on screen (no flicker) — state is only replaced on success.
    const isInitialLoad = !initialLoadDone.current;

    if (isInitialLoad) {
      setLoading(true);
    }

    try {
      const [
        readingData,
        eventsData,
      ] = await Promise.all([
        getCurrentReading(),
        getEvents(10),
      ]);

      setReading(readingData);
      setEvents(eventsData.events);

      setError(null);
    } catch (err) {
      console.error(
        "Failed to load monitoring data:",
        err
      );

      // On a failed poll the previous reading stays rendered; only the
      // error banner is shown.
      setError(
        "Unable to connect to NEXUS API"
      );
    } finally {
      if (isInitialLoad) {
        initialLoadDone.current = true;
        setLoading(false);
      }
    }
  }

  async function loadHistory() {
    try {
      const history = await getHistory(50);

      const formattedHistory: PowerHistoryPoint[] =
        history.map((item) => ({
          time: new Date(
            item.timestamp
          ).toLocaleTimeString("pt-BR", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
          power: item.active_power,
        }));

      setPowerHistory(formattedHistory);
    } catch (err) {
      console.error(
        "Failed to load monitoring history:",
        err
      );
    }
  }

  useEffect(() => {
    // Defer the initial fetch so setState isn't called synchronously
    // inside the effect body (react-hooks/set-state-in-effect).
    queueMicrotask(() => {
      loadReading();
      loadHistory();
    });

    const interval = setInterval(() => {
      loadReading();
      loadHistory();
    }, 5000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  const voltage = reading?.voltage;
  const current = reading?.current;
  const activePower = reading?.active_power;
  const powerFactor = reading?.power_factor;
  const frequency = reading?.frequency;
  const temperature = reading?.temperature;

  const voltageNormal =
    voltage !== undefined &&
    voltage >= 198 &&
    voltage <= 242;

  const frequencyNormal =
    frequency !== undefined &&
    frequency >= 59.5 &&
    frequency <= 60.5;

  const powerFactorNormal =
    powerFactor !== undefined &&
    powerFactor >= 0.8;

  const temperatureNormal =
    temperature !== undefined &&
    temperature <= 70;

  const systemNormal =
    reading?.status === "normal";

  return (
    <div className="space-y-5">




            {error && (
              <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-400">
                <AlertTriangle size={16} />
                {error}
              </div>
            )}

            {/* METRICS */}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">

              <MetricCard
                icon={Gauge}
                label="Voltage"
                value={
                  loading ||
                  voltage === undefined
                    ? "--"
                    : voltage.toFixed(1)
                }
                unit="V"
                status={
                  voltageNormal
                    ? "live"
                    : "warning"
                }
              />

              <MetricCard
                icon={Activity}
                label="Current"
                value={
                  loading ||
                  current === undefined
                    ? "--"
                    : current.toFixed(1)
                }
                unit="A"
              />

              <MetricCard
                icon={Zap}
                label="Active Power"
                value={
                  loading ||
                  activePower === undefined
                    ? "--"
                    : activePower.toFixed(2)
                }
                unit="kW"
              />

              <MetricCard
                icon={Cpu}
                label="Power Factor"
                value={
                  loading ||
                  powerFactor === undefined
                    ? "--"
                    : powerFactor.toFixed(2)
                }
                unit="PF"
                status={
                  powerFactorNormal
                    ? "live"
                    : "warning"
                }
              />

            </div>

            {/* POWER CHART */}
            <div
              id="power-chart"
              className="scroll-mt-6 rounded-2xl border border-white/10 bg-[#111318] p-5 sm:p-6"
            >

              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
                    Energy consumption
                  </p>

                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-2xl font-semibold">
                      {activePower !== undefined
                        ? activePower.toFixed(2)
                        : "--"}
                    </span>

                    <span className="text-sm text-gray-500">
                      kW
                    </span>

                    <span className="ml-1 text-xs text-emerald-400">
                      Live
                    </span>
                  </div>
                </div>

                <div className="rounded-lg border border-white/5 bg-[#15171c] px-3 py-2 text-xs text-gray-400">
                  Last 50 readings
                </div>
              </div>

              <div className="mt-6 h-[280px] w-full">
                {powerHistory.length > 0 ? (
                  <ResponsiveContainer
                    width="100%"
                    height="100%"
                  >
                    <AreaChart
                      data={powerHistory}
                      margin={{
                        top: 10,
                        right: 5,
                        left: -20,
                        bottom: 0,
                      }}
                    >
                      <defs>
                        <linearGradient
                          id="powerGradient"
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="1"
                        >
                          <stop
                            offset="0%"
                            stopColor="#ffffff"
                            stopOpacity={0.16}
                          />

                          <stop
                            offset="100%"
                            stopColor="#ffffff"
                            stopOpacity={0}
                          />
                        </linearGradient>
                      </defs>

                      <CartesianGrid
                        stroke="#ffffff"
                        strokeOpacity={0.05}
                        vertical={false}
                      />

                      <XAxis
                        dataKey="time"
                        tick={{
                          fill: "#5f6673",
                          fontSize: 10,
                        }}
                        axisLine={false}
                        tickLine={false}
                        minTickGap={35}
                      />

                      <YAxis
                        tick={{
                          fill: "#5f6673",
                          fontSize: 10,
                        }}
                        axisLine={false}
                        tickLine={false}
                        domain={["auto", "auto"]}
                      />

                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#15171c",
                          border:
                            "1px solid rgba(255,255,255,0.08)",
                          borderRadius: "10px",
                          color: "#ffffff",
                        }}
                        labelStyle={{
                          color: "#9ca3af",
                          marginBottom: "4px",
                        }}
                        formatter={(value) => [
                          `${Number(value).toFixed(2)} kW`,
                          "Active Power",
                        ]}
                      />

                      <Area
                        type="monotone"
                        dataKey="power"
                        stroke="#e5e7eb"
                        strokeWidth={2}
                        fill="url(#powerGradient)"
                        dot={false}
                        activeDot={{
                          r: 4,
                          strokeWidth: 0,
                        }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-gray-600">
                    Waiting for monitoring data...
                  </div>
                )}
              </div>
            </div>

            {/* LOWER GRID */}
            <div className="grid gap-5 xl:grid-cols-2">

              {/* DIAGNOSTICS */}
              <div className="rounded-2xl border border-white/10 bg-[#111318] p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
                      Diagnostics
                    </p>

                    <h3 className="mt-1 text-lg font-semibold">
                      System parameters
                    </h3>
                  </div>

                  <div
                    className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs ${
                      systemNormal
                        ? "bg-emerald-500/10 text-emerald-400"
                        : "bg-amber-500/10 text-amber-400"
                    }`}
                  >
                    {systemNormal ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <AlertTriangle size={14} />
                    )}

                    {systemNormal
                      ? "Normal"
                      : "Attention"}
                  </div>
                </div>

                <div className="mt-5 space-y-2">
                  <DiagnosticItem
                    label="Voltage"
                    value={
                      voltage !== undefined
                        ? voltage.toFixed(1)
                        : "--"
                    }
                    unit="V"
                    normal={voltageNormal}
                  />

                  <DiagnosticItem
                    label="Frequency"
                    value={
                      frequency !== undefined
                        ? frequency.toFixed(2)
                        : "--"
                    }
                    unit="Hz"
                    normal={frequencyNormal}
                  />

                  <DiagnosticItem
                    label="Power factor"
                    value={
                      powerFactor !== undefined
                        ? powerFactor.toFixed(2)
                        : "--"
                    }
                    unit="PF"
                    normal={powerFactorNormal}
                  />

                  <DiagnosticItem
                    label="Temperature"
                    value={
                      temperature !== undefined
                        ? temperature.toFixed(1)
                        : "--"
                    }
                    unit="°C"
                    normal={temperatureNormal}
                  />
                </div>
              </div>

              {/* SYSTEM INFO */}
              <div className="rounded-2xl border border-white/10 bg-[#111318] p-5">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
                    Monitoring status
                  </p>

                  <h3 className="mt-1 text-lg font-semibold">
                    Real-time telemetry
                  </h3>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-2">

                  <div className="rounded-xl border border-white/5 bg-[#0d0f13] p-4">
                    <div className="flex items-center gap-2 text-gray-400">
                      <Radio size={16} />

                      <span className="text-xs">
                        API connection
                      </span>
                    </div>

                    <p
                      className={`mt-3 text-sm font-medium ${
                        error
                          ? "text-amber-400"
                          : "text-emerald-400"
                      }`}
                    >
                      {error
                        ? "Disconnected"
                        : "Connected"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/5 bg-[#0d0f13] p-4">
                    <div className="flex items-center gap-2 text-gray-400">
                      <Activity size={16} />

                      <span className="text-xs">
                        Sampling
                      </span>
                    </div>

                    <p className="mt-3 text-sm font-medium text-white">
                      Every second
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/5 bg-[#0d0f13] p-4">
                    <div className="flex items-center gap-2 text-gray-400">
                      <Thermometer size={16} />

                      <span className="text-xs">
                        Temperature
                      </span>
                    </div>

                    <p className="mt-3 text-sm font-medium text-white">
                      {temperature !== undefined
                        ? `${temperature.toFixed(1)} °C`
                        : "--"}
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/5 bg-[#0d0f13] p-4">
                    <div className="flex items-center gap-2 text-gray-400">
                      <DatabaseIcon />

                      <span className="text-xs">
                        Stored readings
                      </span>
                    </div>

                    <p className="mt-3 text-sm font-medium text-white">
                      {powerHistory.length}
                    </p>
                  </div>

                </div>
              </div>

            </div>

            {/* RECENT EVENTS */}
            <div
              id="events"
              className="scroll-mt-6 rounded-2xl border border-white/10 bg-[#111318] p-5"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
                    Recent events
                  </p>

                  <h3 className="mt-1 text-lg font-semibold">
                    Monitoring activity
                  </h3>
                </div>

                <Bell
                  size={18}
                  className="text-gray-500"
                />
              </div>

              <div className="mt-5 divide-y divide-white/[0.05]">
                {events.length === 0 ? (
                  <div className="py-6 text-center text-xs text-zinc-600">
                    No events recorded
                  </div>
                ) : (
                  events.map((event) => (
                    <div
                      key={event.id}
                      className="flex items-center gap-4 py-4 first:pt-0 last:pb-0"
                    >
                      <span className="w-10 shrink-0 text-[11px] font-medium text-zinc-600">
                        {new Date(
                          event.timestamp
                        ).toLocaleTimeString(
                          "pt-BR",
                          {
                            hour: "2-digit",
                            minute: "2-digit",
                          }
                        )}
                      </span>

                      <div
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                          event.severity === "high"
                            ? "bg-red-400/10 text-red-400"
                            : event.severity === "medium"
                              ? "bg-amber-400/10 text-amber-400"
                              : "bg-emerald-400/10 text-emerald-400"
                        }`}
                      >
                        {event.severity === "high" ? (
                          <AlertTriangle size={15} />
                        ) : event.severity === "medium" ? (
                          <AlertTriangle size={15} />
                        ) : (
                          <CheckCircle2 size={15} />
                        )}
                      </div>

                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-zinc-300">
                          {event.event_type}
                        </p>

                        <p className="mt-0.5 truncate text-[11px] text-zinc-600">
                          {event.message}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

    </div>
  );
}

function DatabaseIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <ellipse
        cx="12"
        cy="5"
        rx="8"
        ry="3"
      />

      <path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />

      <path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7" />
    </svg>
  );
}
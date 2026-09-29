"use client";

import { useState } from "react";
import { CheckCircle2, FlaskConical, Loader2 } from "lucide-react";
import type { ElementType } from "react";

import {
  ApiError,
  getCurrentReading,
  getSimulationMode,
  setSimulationMode,
} from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import type { SimulationMode } from "../../types/monitoring";
import {
  Card,
  CardHeader,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

const MODES: { value: SimulationMode; icon: ElementType }[] = [
  { value: "normal", icon: CheckCircle2 },
  { value: "high_voltage", icon: FlaskConical },
  { value: "low_voltage", icon: FlaskConical },
  { value: "low_power_factor", icon: FlaskConical },
  { value: "high_temperature", icon: FlaskConical },
  { value: "multiple_anomalies", icon: FlaskConical },
];

export default function SimulationPage() {
  const { t, preferences } = usePreferences();
  const {
    data: currentMode,
    error: loadError,
    loading,
    refresh,
  } = usePoll(getSimulationMode, 10000, t.simulation.changeError);

  const [changing, setChanging] = useState<SimulationMode | null>(null);
  const [changeError, setChangeError] = useState<string | null>(null);

  // Leitura atual para mostrar o efeito do modo em tempo real.
  const { data: reading } = usePoll(
    getCurrentReading,
    preferences.pollingIntervalMs,
    t.common.connectionError
  );

  async function handleSelect(mode: SimulationMode) {
    if (mode === currentMode || changing) {
      return;
    }
    setChanging(mode);
    setChangeError(null);
    try {
      await setSimulationMode(mode);
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setChangeError(t.common.unauthorized);
      } else {
        setChangeError(
          err instanceof Error ? err.message : t.simulation.changeError
        );
      }
    } finally {
      setChanging(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.simulation.title}
        subtitle={t.simulation.subtitle}
      />

      {loadError && <ErrorBanner message={loadError} onRetry={refresh} />}
      {changeError && <ErrorBanner message={changeError} />}

      {loading && !currentMode ? (
        <LoadingState />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {MODES.map(({ value, icon: Icon }) => {
            const active = value === currentMode;
            const busy = changing === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => handleSelect(value)}
                disabled={changing !== null}
                className={`panel density-pad rounded-2xl text-left transition ${
                  active
                    ? "ring-2 ring-[var(--info)]"
                    : "hover:border-[var(--faint)]"
                } disabled:cursor-wait disabled:opacity-70`}
              >
                <div className="flex items-center justify-between">
                  <div
                    className={`flex h-11 w-11 items-center justify-center rounded-xl ${
                      active
                        ? "bg-[var(--info)] text-white"
                        : "bg-surface-3 text-muted"
                    }`}
                  >
                    {busy ? (
                      <Loader2 size={20} className="animate-spin" />
                    ) : (
                      <Icon size={20} />
                    )}
                  </div>
                  {active && (
                    <span className="rounded-full bg-[var(--info)] px-3 py-1 text-xs font-medium text-white">
                      {t.simulation.currentMode}
                    </span>
                  )}
                </div>
                <p className="mt-4 text-sm font-semibold text-ink">
                  {t.simulation.modes[value]}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {t.simulation.modeDescriptions[value]}
                </p>
              </button>
            );
          })}
        </div>
      )}

      <Card>
        <CardHeader
          eyebrow={t.simulation.title}
          title={t.simulation.liveEffect}
        />
        {reading && (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: t.dashboard.voltage, value: `${formatNumber(reading.voltage, 1)} V` },
              { label: t.dashboard.current, value: `${formatNumber(reading.current, 1)} A` },
              { label: t.dashboard.activePower, value: `${formatNumber(reading.active_power, 2)} kW` },
              { label: t.dashboard.temperature, value: `${formatNumber(reading.temperature, 1)} °C` },
            ].map((m) => (
              <div
                key={m.label}
                className="rounded-xl bg-surface-2 px-4 py-3"
              >
                <p className="text-[11px] uppercase tracking-wider text-faint">
                  {m.label}
                </p>
                <p className="mt-1 text-sm font-semibold text-ink">
                  {m.value}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

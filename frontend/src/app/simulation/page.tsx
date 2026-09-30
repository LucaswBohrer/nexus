"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  History,
  Loader2,
  Play,
  Radio,
  RotateCcw,
  Square,
  Thermometer,
  Waves,
  Zap,
  ZapOff,
} from "lucide-react";
import type { ElementType } from "react";

import {
  getSimulationSessions,
  getSimulationStatus,
  resetSimulation,
  startSimulation,
  stopSimulation,
} from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { useEquipment } from "../../lib/equipment";
import { usePreferences } from "../../lib/preferences";
import { errorMessage, usePoll } from "../../lib/usePoll";
import type {
  AnomalyKey,
  SimulationMode,
  SimulationSession,
} from "../../types/monitoring";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";
import { EquipmentContextLine } from "../../components/EquipmentContext";

const PRESETS: { value: SimulationMode; icon: ElementType }[] = [
  { value: "normal", icon: CheckCircle2 },
  { value: "high_voltage", icon: Zap },
  { value: "low_voltage", icon: ZapOff },
  { value: "low_power_factor", icon: Activity },
  { value: "high_temperature", icon: Thermometer },
  { value: "multiple_anomalies", icon: FlaskConical },
  { value: "sensor_failure", icon: Radio },
  { value: "oscillation", icon: Waves },
  { value: "overload", icon: AlertTriangle },
];

/** Anomalias combináveis no composer (falha de sensor é rejeitada pelo backend). */
const COMPOSABLE_ANOMALIES: AnomalyKey[] = [
  "high_voltage",
  "low_voltage",
  "low_power_factor",
  "high_temperature",
  "overload",
  "oscillation",
];

const DURATION_PRESETS: (number | "none" | "custom")[] = [
  "none",
  1,
  5,
  15,
  30,
  "custom",
];

const PEAK_METRICS = ["voltage", "current", "active_power", "temperature"] as const;

function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function formatDuration(totalSeconds: number | null): string {
  if (totalSeconds === null || totalSeconds < 0) return "—";
  const s = Math.floor(totalSeconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60 > 0 ? ` ${m % 60}min` : ""}`;
}

export default function SimulationPage() {
  const { t, preferences } = usePreferences();
  const { equipmentId, equipment } = useEquipment();

  // Status e sessões são escopados ao equipamento selecionado. A
  // simulação continua sendo um fluxo global único no backend; start
  // carrega o equipment_id e stop/reset escopados retornam 409 em caso
  // de divergência com a sessão ativa.
  const {
    data: status,
    error: statusError,
    loading: statusLoading,
    refresh: refreshStatus,
  } = usePoll(
    () => getSimulationStatus(equipmentId),
    2000,
    t.simulation.statusError,
    equipmentId
  );

  // --- Countdown local, sempre ressincronizado com o backend ---
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    function syncFromBackend() {
      setRemaining(status?.remaining_seconds ?? null);
    }
    syncFromBackend();
  }, [status]);

  const ticking = remaining !== null && remaining > 0;
  useEffect(() => {
    if (!ticking) return;
    const id = window.setInterval(() => {
      setRemaining((r) => (r !== null && r > 0 ? r - 1 : r));
    }, 1000);
    return () => window.clearInterval(id);
  }, [ticking]);

  // --- Histórico de sessões (declarado cedo: o countdown usa loadSessions) ---
  const [sessions, setSessions] = useState<SimulationSession[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadSessions = useCallback(
    async (cursor?: number | null, append = false) => {
      if (append) {
        setLoadingMore(true);
      } else {
        setSessionsLoading(true);
      }
      setSessionsError(null);
      try {
        const page = await getSimulationSessions(
          20,
          cursor ?? undefined,
          equipmentId
        );
        setSessions((prev) => (append ? [...prev, ...page.sessions] : page.sessions));
        setNextCursor(page.next_cursor);
      } catch (err) {
        setSessionsError(errorMessage(err, t.simulation.sessionsError));
      } finally {
        setSessionsLoading(false);
        setLoadingMore(false);
      }
    },
    [t, equipmentId]
  );

  const refreshSessions = useCallback(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    function initialLoad() {
      void loadSessions();
    }
    initialLoad();
    const id = window.setInterval(() => void loadSessions(), 30_000);
    return () => window.clearInterval(id);
  }, [loadSessions]);

  // Quando o countdown chega a zero, busca o estado real (auto-revert do backend).
  const zeroSyncedRef = useRef(false);
  useEffect(() => {
    if (remaining === 0 && !zeroSyncedRef.current) {
      zeroSyncedRef.current = true;
      const id = window.setTimeout(() => {
        refreshStatus();
        refreshSessions();
      }, 800);
      return () => window.clearTimeout(id);
    }
    if (remaining !== 0) {
      zeroSyncedRef.current = false;
    }
  }, [remaining, refreshStatus, refreshSessions]);

  // --- Configuração do cenário ---
  const [mode, setMode] = useState<SimulationMode>("high_voltage");
  const [intensity, setIntensity] = useState(100);
  const [duration, setDuration] = useState<number | "none" | "custom">("none");
  const [customMinutes, setCustomMinutes] = useState("10");
  const [anomalies, setAnomalies] = useState<AnomalyKey[]>([]);

  // --- Ações ---
  const [busy, setBusy] = useState<"start" | "stop" | "reset" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  function toggleAnomaly(key: AnomalyKey) {
    setAnomalies((prev) =>
      prev.includes(key) ? prev.filter((a) => a !== key) : [...prev, key]
    );
  }

  async function runAction(
    kind: "start" | "stop" | "reset",
    fn: () => Promise<unknown>
  ) {
    if (busy) return;
    setBusy(kind);
    setActionError(null);
    try {
      await fn();
      refreshStatus();
      refreshSessions();
    } catch (err) {
      const fallback =
        kind === "start"
          ? t.simulation.startError
          : kind === "stop"
            ? t.simulation.stopError
            : t.simulation.resetError;
      setActionError(errorMessage(err, fallback));
    } finally {
      setBusy(null);
    }
  }

  function handleStart() {
    const custom = duration === "custom" ? Number(customMinutes) : undefined;
    const durationMinutes =
      duration === "none" ? null : duration === "custom" ? custom : duration;
    runAction("start", () =>
      startSimulation({
        mode,
        intensity,
        duration_minutes: durationMinutes,
        anomalies: mode === "sensor_failure" ? [] : anomalies,
        equipment_id: equipmentId,
      })
    );
  }

  const running = status?.running === true;
  const composerDisabled = mode === "sensor_failure";
  // Equipamento desativado recusa writes no backend (409): o Iniciar é
  // bloqueado aqui com mensagem honesta; Parar/Reset são ações de
  // recuperação e o backend decide.
  const writesBlocked = equipment !== null && !equipment.enabled;

  return (
    <div className="space-y-5">
      <EquipmentContextLine />
      <PageHeader
        title={t.simulation.title}
        subtitle={t.simulation.subtitle}
      />

      {statusError && (
        <ErrorBanner message={statusError} onRetry={refreshStatus} />
      )}
      {actionError && <ErrorBanner message={actionError} />}
      {writesBlocked && equipment && (
        <Card>
          <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-[var(--warn)]">
            {t.equipment.writeBlocked} ({equipment.name} · {equipment.code})
          </p>
        </Card>
      )}

      {/* --- Status atual --- */}
      <Card>
        <CardHeader
          eyebrow={t.simulation.statusTitle}
          title={running ? t.simulation.running : t.simulation.idle}
          action={
            <Badge tone={running ? "warning" : "normal"}>
              {running ? t.simulation.running : t.simulation.idle}
            </Badge>
          }
        />
        {statusLoading && !status ? (
          <LoadingState />
        ) : status ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-faint">{t.simulation.mode}</dt>
              <dd className="mt-1 font-medium text-ink">
                {t.simulation.modes[status.mode]}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">{t.simulation.intensity}</dt>
              <dd className="mt-1 font-medium text-ink">
                {formatNumber(status.intensity, 0)}%
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">{t.simulation.remaining}</dt>
              <dd className="mt-1 font-mono text-lg font-semibold text-ink">
                {status.running && status.remaining_seconds !== null
                  ? formatCountdown(remaining ?? status.remaining_seconds)
                  : status.ends_at === null && status.running
                    ? t.simulation.indefinite
                    : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">{t.simulation.anomalies}</dt>
              <dd className="mt-1 font-medium text-ink">
                {status.anomalies.length > 0
                  ? status.anomalies.join(", ")
                  : t.simulation.none}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">{t.simulation.startedAt}</dt>
              <dd className="mt-1 text-muted">
                {status.started_at ? formatDateTime(status.started_at, preferences) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">{t.simulation.endsAt}</dt>
              <dd className="mt-1 text-muted">
                {status.ends_at ? formatDateTime(status.ends_at, preferences) : "—"}
              </dd>
            </div>
          </dl>
        ) : null}
        <p className="mt-4 text-xs text-faint">{t.simulation.liveEffect}</p>
      </Card>

      {/* --- Configuração --- */}
      <Card>
        <CardHeader
          eyebrow={t.simulation.configTitle}
          title={t.simulation.presetsTitle}
        />
        <p className="mt-1 text-xs text-faint">{t.simulation.selectPresetHint}</p>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {PRESETS.map(({ value, icon: Icon }) => {
            const active = value === mode;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                aria-pressed={active}
                className={`flex min-h-[64px] items-center gap-3 rounded-2xl border px-4 py-3 text-left transition ${
                  active
                    ? "border-[var(--info)] ring-2 ring-[var(--info)]/40"
                    : "border-transparent hover:border-[var(--faint)]"
                } bg-surface-2`}
              >
                <span
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                    active
                      ? "bg-[var(--info)] text-white"
                      : "bg-surface-3 text-muted"
                  }`}
                >
                  <Icon size={20} />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ink">
                    {t.simulation.modes[value]}
                  </span>
                  <span className="block truncate text-xs text-faint">
                    {t.simulation.modeDescriptions[value]}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {/* Intensidade */}
        <div className="mt-6">
          <div className="flex items-baseline justify-between">
            <label
              htmlFor="sim-intensity"
              className="text-sm font-medium text-ink"
            >
              {t.simulation.intensityLabel}
            </label>
            <span className="font-mono text-lg font-semibold text-ink">
              {intensity}%
            </span>
          </div>
          <input
            id="sim-intensity"
            type="range"
            min={0}
            max={200}
            step={5}
            value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))}
            className="mt-2 h-11 w-full accent-[var(--info)]"
          />
          <p className="mt-1 text-xs text-faint">{t.simulation.intensityHint}</p>
        </div>

        {/* Duração */}
        <div className="mt-6">
          <p className="text-sm font-medium text-ink">
            {t.simulation.durationLabel}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {DURATION_PRESETS.map((d) => {
              const active = duration === d;
              const label =
                d === "none"
                  ? t.simulation.durationNone
                  : d === "custom"
                    ? t.simulation.durationCustom
                    : `${d} min`;
              return (
                <button
                  key={String(d)}
                  type="button"
                  onClick={() => setDuration(d)}
                  aria-pressed={active}
                  className={`min-h-[44px] rounded-xl px-4 py-2 text-sm font-medium transition ${
                    active
                      ? "bg-[var(--info)] text-white"
                      : "bg-surface-3 text-muted hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {duration === "custom" && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="number"
                min={0.05}
                step={0.5}
                value={customMinutes}
                onChange={(e) => setCustomMinutes(e.target.value)}
                aria-label={t.simulation.durationMinutes}
                className="h-11 w-32 rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink"
              />
              <span className="text-sm text-muted">
                {t.simulation.durationMinutes}
              </span>
            </div>
          )}
          <p className="mt-2 text-xs text-faint">{t.simulation.durationHint}</p>
        </div>

        {/* Composer */}
        <div className="mt-6">
          <p className="text-sm font-medium text-ink">
            {t.simulation.composerTitle}
          </p>
          <p className="mt-1 text-xs text-faint">
            {composerDisabled
              ? t.simulation.composerDisabledSensor
              : t.simulation.composerHint}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {COMPOSABLE_ANOMALIES.map((key) => {
              const active = anomalies.includes(key);
              return (
                <button
                  key={key}
                  type="button"
                  disabled={composerDisabled}
                  onClick={() => toggleAnomaly(key)}
                  aria-pressed={active}
                  className={`min-h-[44px] rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    active
                      ? "bg-[var(--warning)] text-white"
                      : "bg-surface-3 text-muted hover:text-ink"
                  }`}
                >
                  {t.simulation.modes[key]}
                </button>
              );
            })}
          </div>
        </div>

        {/* Controles */}
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <button
            type="button"
            onClick={handleStart}
            disabled={busy !== null || writesBlocked}
            title={writesBlocked ? t.equipment.writeBlocked : undefined}
            className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl bg-[var(--info)] px-6 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy === "start" ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Play size={18} />
            )}
            {busy === "start" ? t.simulation.starting : t.simulation.start}
          </button>
          <button
            type="button"
            onClick={() => runAction("stop", () => stopSimulation(equipmentId))}
            disabled={busy !== null}
            className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl bg-surface-3 px-6 text-sm font-semibold text-ink transition disabled:cursor-wait disabled:opacity-60"
          >
            {busy === "stop" ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Square size={18} />
            )}
            {busy === "stop" ? t.simulation.stopping : t.simulation.stop}
          </button>
          <button
            type="button"
            onClick={() => runAction("reset", () => resetSimulation(equipmentId))}
            disabled={busy !== null}
            className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl bg-surface-3 px-6 text-sm font-semibold text-ink transition disabled:cursor-wait disabled:opacity-60"
          >
            {busy === "reset" ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <RotateCcw size={18} />
            )}
            {busy === "reset" ? t.simulation.resetting : t.simulation.reset}
          </button>
        </div>
      </Card>

      {/* --- Histórico --- */}
      <Card>
        <CardHeader
          eyebrow={t.simulation.historyTitle}
          title={`${t.simulation.historyTitle} · ${sessions.length}`}
          action={
            <button
              type="button"
              onClick={refreshSessions}
              aria-label={t.simulation.historyTitle}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl bg-surface-3 px-4 text-sm font-medium text-muted transition hover:text-ink"
            >
              <History size={16} />
            </button>
          }
        />
        {sessionsError && (
          <ErrorBanner message={sessionsError} onRetry={refreshSessions} />
        )}
        {sessionsLoading && sessions.length === 0 ? (
          <LoadingState />
        ) : sessions.length === 0 ? (
          <EmptyState
            icon={FlaskConical}
            title={t.simulation.historyTitle}
            message={t.simulation.historyEmpty}
          />
        ) : (
          <ul className="mt-4 space-y-3">
            {sessions.map((session) => (
              <SessionCard key={session.id} session={session} />
            ))}
          </ul>
        )}
        {nextCursor !== null && sessions.length > 0 && (
          <button
            type="button"
            onClick={() => void loadSessions(nextCursor, true)}
            disabled={loadingMore}
            className="mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-2xl bg-surface-3 text-sm font-semibold text-ink transition disabled:opacity-60"
          >
            {loadingMore && <Loader2 size={16} className="animate-spin" />}
            {t.simulation.loadMore}
          </button>
        )}
      </Card>
    </div>
  );
}

function SessionCard({ session }: { session: SimulationSession }) {
  const { t, preferences } = usePreferences();
  const params = session.parameters;
  const tone =
    session.status === "running"
      ? "info"
      : session.status === "finished"
        ? "normal"
        : "warning";
  const statusLabel =
    session.status === "running"
      ? t.simulation.sessionRunning
      : session.status === "finished"
        ? t.simulation.sessionFinished
        : t.simulation.sessionInterrupted;

  const peaks = session.peak_values
    ? PEAK_METRICS.filter((m) => session.peak_values?.[m])
        .map((m) => {
          const p = session.peak_values?.[m];
          return p
            ? `${m}: ${formatNumber(p.min, 1)}–${formatNumber(p.max, 1)}`
            : "";
        })
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <li className="rounded-2xl bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-faint">
            {t.simulation.session} #{session.id}
          </span>
          <Badge tone={tone}>{statusLabel}</Badge>
        </div>
        <span className="text-xs text-faint">
          {formatDateTime(session.started_at, preferences)}
          {session.ended_at ? ` → ${formatDateTime(session.ended_at, preferences)}` : ""}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-faint">{t.simulation.mode}</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {t.simulation.modes[session.mode] ?? session.mode}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-faint">{t.simulation.intensity}</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {params ? `${formatNumber(params.intensity, 0)}%` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-faint">{t.simulation.duration}</dt>
          <dd className="mt-0.5 font-medium text-ink">
            {formatDuration(session.duration_s)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-faint">{t.simulation.peaks}</dt>
          <dd className="mt-0.5 text-xs text-muted">{peaks || "—"}</dd>
        </div>
      </dl>
    </li>
  );
}

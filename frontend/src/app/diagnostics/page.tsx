"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Stethoscope, TriangleAlert } from "lucide-react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getEquipmentDiagnosis,
  getEpisodes,
  getHistoryBuckets,
  getSettings,
} from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { useEquipment } from "../../lib/equipment";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import type {
  DiagnosticEpisode,
  HistoryBucket,
  HistoryMetric,
  SettingValue,
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

const THRESHOLD_KEYS = [
  "thresholds.voltage_min",
  "thresholds.voltage_max",
  "thresholds.frequency_min",
  "thresholds.frequency_max",
  "thresholds.power_factor_min",
  "thresholds.temperature_max",
] as const;

function bucketForRange(fromMs: number, toMs: number): "5m" | "15m" | "1h" | "1d" {
  const hours = (toMs - fromMs) / 3600_000;
  if (hours <= 6) {
    return "5m";
  }
  if (hours <= 48) {
    return "15m";
  }
  if (hours <= 24 * 14) {
    return "1h";
  }
  return "1d";
}

function EpisodeHistory({
  episode,
  metric,
  equipmentId,
}: {
  episode: DiagnosticEpisode;
  metric: string;
  equipmentId: number | null;
}) {
  const { t } = usePreferences();
  const [buckets, setBuckets] = useState<HistoryBucket[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const fromMs = new Date(episode.started_at).getTime();
        const toMs = episode.ended_at
          ? new Date(episode.ended_at).getTime()
          : Date.now();
        const data = await getHistoryBuckets({
          metric: metric as HistoryMetric,
          from: new Date(fromMs).toISOString(),
          to: new Date(toMs).toISOString(),
          bucket: bucketForRange(fromMs, toMs),
          equipmentId,
        });
        if (!cancelled) {
          setBuckets(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t.common.noData);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [episode, metric, equipmentId, t]);

  if (error) {
    return <p className="py-6 text-center text-xs text-faint">{error}</p>;
  }
  if (buckets.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-faint">
        {t.common.waitingData}
      </p>
    );
  }

  return (
    <div className="mt-3 h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={buckets.map((b) => ({
            label: new Date(b.t).toLocaleString("pt-BR", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            }),
            avg: b.avg,
            range: [b.min, b.max],
          }))}
          margin={{ top: 8, right: 5, left: -18, bottom: 0 }}
        >
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "var(--faint)", fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            minTickGap={50}
          />
          <YAxis
            tick={{ fill: "var(--faint)", fontSize: 9 }}
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
            formatter={(value) => [`${formatNumber(Number(value), 2)}`, metric]}
          />
          <Line
            type="monotone"
            dataKey="avg"
            stroke="var(--warn)"
            strokeWidth={2}
            dot={false}
            name="avg"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function EpisodeCard({
  episode,
  equipmentId,
}: {
  episode: DiagnosticEpisode;
  equipmentId: number | null;
}) {
  const { t, preferences } = usePreferences();
  const [expanded, setExpanded] = useState(false);

  const peakEntries = useMemo(
    () => Object.entries(episode.peak_values),
    [episode]
  );
  const chartMetric = peakEntries[0]?.[0];

  return (
    <div className="rounded-xl bg-surface-2 px-4 py-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex min-h-[44px] w-full items-center gap-2 text-left"
      >
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <Badge tone={episode.severity}>{t.status[episode.severity]}</Badge>
          <Badge tone={episode.status === "open" ? "open" : "resolved"}>
            {episode.status === "open"
              ? t.diagnostics.episodeOpen
              : t.diagnostics.episodeResolved}
          </Badge>
          <span className="text-xs text-faint">
            #{episode.id} · {formatDateTime(episode.started_at, preferences)}
            {episode.ended_at &&
              ` → ${formatDateTime(episode.ended_at, preferences)}`}
          </span>
        </div>
        <ChevronDown
          size={18}
          className={`shrink-0 text-faint transition-transform ${
            expanded ? "rotate-180" : ""
          }`}
        />
      </button>

      <p className="mt-2 text-xs text-muted">
        {t.diagnostics.rules}: {episode.rules.join(", ")}
      </p>

      {expanded && (
        <div className="mt-3 border-t border-[var(--border)] pt-3">
          {peakEntries.length > 0 && (
            <>
              <p className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">
                {t.diagnostics.peakValues}
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {peakEntries.map(([metric, peak]) => (
                  <div
                    key={metric}
                    className="rounded-lg bg-surface-3 px-3 py-2"
                  >
                    <p className="text-[11px] uppercase tracking-wider text-faint">
                      {metric}
                    </p>
                    <p className="mt-0.5 text-sm font-semibold text-ink">
                      {formatNumber(peak.min, 1)} – {formatNumber(peak.max, 1)}
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}

          {chartMetric && (
            <EpisodeHistory
              episode={episode}
              metric={chartMetric}
              equipmentId={equipmentId}
            />
          )}

          {episode.recommendations.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">
                {t.diagnostics.recommendations}
              </p>
              {episode.recommendations.map((rec, i) => (
                <p key={i} className="text-sm text-muted">
                  • {rec}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DiagnosticsPage() {
  const { t, preferences } = usePreferences();
  const { equipmentId } = useEquipment();

  // O endpoint legado /api/monitoring/diagnostics não tem escopo por
  // equipamento: o diagnóstico vem do Equipment Summary. Um equipamento
  // sem leituras ainda não tem diagnóstico — estado honesto, não erro.
  const diagPoll = usePoll(
    async () => {
      try {
        // Sem leituras ainda, o summary não tem diagnóstico: fallback
        // determinístico para DEFAULT enquanto o contexto carrega.
        return await getEquipmentDiagnosis(equipmentId ?? "DEFAULT");
      } catch (err) {
        if (err instanceof Error && err.message === "no-data") {
          return null;
        }
        throw err;
      }
    },
    preferences.pollingIntervalMs,
    t.common.connectionError,
    equipmentId
  );
  const episodesPoll = usePoll(
    () => getEpisodes(20, equipmentId),
    30000,
    t.common.connectionError,
    equipmentId
  );
  const settingsPoll = usePoll(getSettings, 0, t.common.connectionError);

  const diagnosis = diagPoll.data?.diagnosis ?? null;
  const episodes = episodesPoll.data ?? [];
  const settings = (settingsPoll.data ?? {}) as Record<string, SettingValue>;

  const error = diagPoll.error ?? episodesPoll.error ?? null;
  const loading = diagPoll.loading && !diagPoll.data;

  return (
    <div className="space-y-5">
      <EquipmentContextLine />
      <PageHeader
        title={t.diagnostics.title}
        subtitle={t.diagnostics.subtitle}
      />

      {error && (
        <ErrorBanner
          message={error}
          onRetry={() => {
            diagPoll.refresh();
            episodesPoll.refresh();
          }}
        />
      )}

      {loading ? (
        <LoadingState />
      ) : (
        <>
          {diagnosis ? (
            <>
              {/* DIAGNÓSTICO ATUAL — 100% backend */}
              <Card>
                <CardHeader
                  eyebrow={t.diagnostics.currentDiagnosis}
                  title={t.diagnostics.currentDiagnosis}
                  action={
                    <Badge tone={diagnosis.severity}>
                      {
                        t.status[
                          diagnosis.status as "normal" | "warning" | "critical"
                        ]
                      }
                    </Badge>
                  }
                />
            {diagnosis.anomalies.length === 0 ? (
              <p className="mt-4 text-sm text-muted">
                {t.dashboard.noAnomalies}
              </p>
            ) : (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-medium uppercase tracking-wider text-faint">
                  {t.diagnostics.anomalies}
                </p>
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
                  <>
                    <p className="pt-2 text-xs font-medium uppercase tracking-wider text-faint">
                      {t.diagnostics.recommendations}
                    </p>
                    {diagnosis.recommendations.map((rec, i) => (
                      <p key={i} className="text-sm text-muted">
                        • {rec}
                      </p>
                    ))}
                  </>
                )}
              </div>
            )}
            <p className="mt-4 text-[11px] text-faint">
              {t.diagnostics.liveNote}
            </p>
          </Card>

          {/* LIMITES USADOS PELO BACKEND — exibidos, não duplicados */}
          <Card>
            <CardHeader
              eyebrow={t.diagnostics.thresholdsTitle}
              title={t.diagnostics.thresholdsTitle}
            />
            <p className="mt-1 text-xs text-faint">
              {t.diagnostics.thresholdsHint}
            </p>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {THRESHOLD_KEYS.map((key) => {
                const raw = settings[key];
                const num =
                  raw === null || raw === undefined ? null : Number(raw);
                return (
                  <div
                    key={key}
                    className="rounded-xl bg-surface-2 px-4 py-3"
                  >
                    <p className="text-[11px] uppercase tracking-wider text-faint">
                      {t.settings.labels[key] ?? key}
                    </p>
                    <p className="mt-1 text-base font-semibold text-ink">
                      {num !== null && Number.isFinite(num)
                        ? formatNumber(num, 2)
                        : "—"}
                    </p>
                  </div>
                );
              })}
            </div>
          </Card>
            </>
          ) : (
            <Card>
              <EmptyState
                icon={Stethoscope}
                title={t.equipment.noLastReading}
                message=""
              />
            </Card>
          )}

          {/* EPISÓDIOS — independentes do diagnóstico atual (retenção maior) */}
          <Card>
            <CardHeader
              eyebrow={t.diagnostics.episodes}
              title={t.diagnostics.episodes}
            />
            {episodes.length === 0 ? (
              <EmptyState
                icon={Stethoscope}
                title={t.diagnostics.noEpisodes}
                message=""
              />
            ) : (
              <div className="mt-4 space-y-3">
                {episodes.map((episode) => (
                  <EpisodeCard
                    key={episode.id}
                    episode={episode}
                    equipmentId={equipmentId}
                  />
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

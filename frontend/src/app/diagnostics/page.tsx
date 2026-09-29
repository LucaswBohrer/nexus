"use client";

import { Stethoscope } from "lucide-react";

import { getDiagnostics, getEpisodes } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

/**
 * Versão básica — a Etapa K adiciona os episódios completos e remove
 * qualquer regra elétrica duplicada do React.
 */
export default function DiagnosticsPage() {
  const { t, preferences } = usePreferences();
  const {
    data: diagnostics,
    error,
    loading,
    refresh,
  } = usePoll(getDiagnostics, preferences.pollingIntervalMs, t.common.connectionError);
  const { data: episodes } = usePoll(
    () => getEpisodes(10),
    30000,
    t.common.connectionError
  );

  const diagnosis = diagnostics?.diagnosis;

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.diagnostics.title}
        subtitle={t.diagnostics.subtitle}
      />

      {error && <ErrorBanner message={error} onRetry={refresh} />}

      {loading && !diagnosis ? (
        <LoadingState />
      ) : diagnosis ? (
        <>
          <Card>
            <CardHeader
              eyebrow={t.diagnostics.currentDiagnosis}
              title={t.diagnostics.currentDiagnosis}
              action={
                <Badge tone={diagnosis.severity}>
                  {t.status[diagnosis.status as "normal" | "warning" | "critical"]}
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
                    className="rounded-xl bg-surface-2 px-4 py-2.5 text-sm text-ink"
                  >
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

          <Card>
            <CardHeader
              eyebrow={t.diagnostics.episodes}
              title={t.diagnostics.episodes}
            />
            {!episodes || episodes.length === 0 ? (
              <EmptyState
                icon={Stethoscope}
                title={t.diagnostics.noEpisodes}
                message=""
              />
            ) : (
              <div className="mt-4 space-y-3">
                {episodes.map((episode) => (
                  <div
                    key={episode.id}
                    className="rounded-xl bg-surface-2 px-4 py-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={episode.severity}>
                        {t.status[episode.severity]}
                      </Badge>
                      <Badge tone={episode.status === "open" ? "open" : "resolved"}>
                        {episode.status === "open"
                          ? t.diagnostics.episodeOpen
                          : t.diagnostics.episodeResolved}
                      </Badge>
                      <span className="ml-auto text-xs text-faint">
                        {formatDateTime(episode.started_at, preferences)}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-muted">
                      {t.diagnostics.rules}: {episode.rules.join(", ")}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}

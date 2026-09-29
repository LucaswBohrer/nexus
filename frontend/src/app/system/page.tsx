"use client";

import { AlertTriangle, ScrollText } from "lucide-react";

import {
  getHealth,
  getSystemDatabase,
  getSystemErrors,
} from "../../lib/api";
import {
  formatBytes,
  formatDateTime,
  formatNumber,
  formatUptime,
} from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <span className="text-sm text-muted">{label}</span>
      <span className="truncate text-sm font-medium text-ink">{value}</span>
    </div>
  );
}

export default function SystemPage() {
  const { t, preferences } = usePreferences();

  const {
    data: health,
    error: healthError,
    loading: healthLoading,
    refresh: refreshHealth,
  } = usePoll(getHealth, 15000, t.common.connectionError);

  const {
    data: database,
    error: dbError,
    loading: dbLoading,
  } = usePoll(getSystemDatabase, 30000, t.common.connectionError);

  const {
    data: errorsData,
    error: errorsError,
    loading: errorsLoading,
  } = usePoll(getSystemErrors, 30000, t.common.connectionError);

  const uptimeTemplates = {
    full: t.time.uptimeFormat,
    short: t.time.uptimeShort,
    minutes: t.time.uptimeMinutes,
  };

  return (
    <div className="space-y-5">
      <PageHeader title={t.system.title} subtitle={t.system.subtitle} />

      {(healthError || dbError || errorsError) && (
        <ErrorBanner
          message={healthError ?? dbError ?? errorsError ?? ""}
          onRetry={refreshHealth}
        />
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader
            eyebrow={t.system.health}
            title={t.system.health}
          />
          {healthLoading && !health ? (
            <LoadingState />
          ) : health ? (
            <div className="mt-2 divide-y divide-[var(--border)]">
              <InfoRow label={t.system.status} value={health.status} />
              <InfoRow label={t.system.version} value={health.version ?? "--"} />
              <InfoRow
                label={t.system.uptime}
                value={formatUptime(health.uptime_s, uptimeTemplates)}
              />
              <InfoRow
                label={t.system.dbSize}
                value={formatBytes(health.db_size_bytes)}
              />
              <InfoRow
                label={t.system.readingsCount}
                value={
                  health.readings_count !== undefined
                    ? formatNumber(health.readings_count, 0)
                    : "--"
                }
              />
              <InfoRow
                label={t.system.lastTick}
                value={
                  health.last_tick_age_ms !== undefined
                    ? `${formatNumber(health.last_tick_age_ms, 0)} ms`
                    : "--"
                }
              />
            </div>
          ) : null}
        </Card>

        <Card>
          <CardHeader
            eyebrow={t.system.database}
            title={t.system.database}
          />
          {dbLoading && !database ? (
            <LoadingState />
          ) : database ? (
            <div className="mt-2 divide-y divide-[var(--border)]">
              <InfoRow label={t.system.path} value={database.path} />
              <InfoRow
                label={t.system.dbSize}
                value={formatBytes(database.size_bytes)}
              />
              <InfoRow
                label={t.system.journalMode}
                value={database.journal_mode}
              />
              <InfoRow
                label={t.system.schemaVersion}
                value={String(database.user_version)}
              />
              <InfoRow
                label={t.system.tables}
                value={database.tables.join(", ")}
              />
            </div>
          ) : null}
        </Card>
      </div>

      <Card>
        <CardHeader eyebrow={t.system.errors} title={t.system.errors} />
        {errorsLoading && !errorsData ? (
          <LoadingState />
        ) : errorsData && errorsData.errors.length > 0 ? (
          <div className="mt-4 space-y-2">
            {errorsData.errors.map((err, i) => (
              <div
                key={`${err.timestamp}-${i}`}
                className="flex items-start gap-3 rounded-xl bg-surface-2 px-4 py-3"
              >
                <AlertTriangle
                  size={16}
                  className="mt-0.5 shrink-0 text-[var(--warn)]"
                />
                <div className="min-w-0">
                  <p className="text-xs text-faint">
                    {formatDateTime(err.timestamp, preferences)}
                  </p>
                  <p className="mt-0.5 break-words text-sm text-ink">
                    {err.message}
                  </p>
                  {err.context && (
                    <p className="mt-0.5 break-words text-xs text-muted">
                      {err.context}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={ScrollText}
            title={t.system.noErrors}
            message=""
          />
        )}
      </Card>

    </div>
  );
}

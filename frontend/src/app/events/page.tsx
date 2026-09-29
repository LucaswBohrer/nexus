"use client";

import { Bell } from "lucide-react";

import { getEventsV1 } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

/**
 * Versão básica — a Etapa I adiciona abas, filtros, busca e
 * reconhecer/resolver via PATCH.
 */
export default function EventsPage() {
  const { t, preferences } = usePreferences();
  const { data, error, loading, refresh } = usePoll(
    () => getEventsV1({ limit: 50 }),
    preferences.pollingIntervalMs,
    t.common.connectionError
  );

  const events = data?.events ?? [];

  return (
    <div className="space-y-5">
      <PageHeader title={t.events.title} subtitle={t.events.subtitle} />

      {error && <ErrorBanner message={error} onRetry={refresh} />}

      {loading && events.length === 0 ? (
        <LoadingState />
      ) : events.length === 0 ? (
        <Card>
          <EmptyState
            icon={Bell}
            title={t.events.noEvents}
            message={t.events.noEventsHint}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {events.map((event) => (
            <Card key={event.id}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={event.severity}>
                  {t.status[event.severity]}
                </Badge>
                <Badge tone={event.status}>
                  {t.status[event.status]}
                </Badge>
                <span className="ml-auto text-xs text-faint">
                  {formatDateTime(event.opened_at ?? event.timestamp, preferences)}
                </span>
              </div>
              <p className="mt-3 text-sm font-medium text-ink">
                {event.event_type}
              </p>
              <p className="mt-1 text-sm text-muted">{event.message}</p>
              <p className="mt-2 text-xs text-faint">
                {t.events.occurrences.replace(
                  "{n}",
                  String(event.occurrences)
                )}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

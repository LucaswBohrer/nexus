"use client";

import { Settings as SettingsIcon } from "lucide-react";

import { getSettings } from "../../lib/api";
import { usePreferences } from "../../lib/preferences";
import { usePoll } from "../../lib/usePoll";
import {
  Card,
  CardHeader,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

/**
 * Versão básica — a Etapa J adiciona edição com validação, seções e
 * preferências locais.
 */
export default function SettingsPage() {
  const { t } = usePreferences();
  const { data, error, loading, refresh } = usePoll(
    getSettings,
    0,
    t.common.connectionError
  );

  const entries = data ? Object.entries(data) : [];

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.settings.title}
        subtitle={t.settings.subtitle}
      />

      {error && <ErrorBanner message={error} onRetry={refresh} />}

      <Card>
        <CardHeader
          eyebrow={t.settings.sections.thresholds}
          title={t.settings.title}
        />
        {loading && entries.length === 0 ? (
          <LoadingState />
        ) : (
          <div className="mt-2 divide-y divide-[var(--border)]">
            {entries.map(([key, value]) => (
              <div
                key={key}
                className="flex items-center justify-between gap-4 py-2.5"
              >
                <span className="font-mono text-xs text-muted">{key}</span>
                <span className="text-sm font-medium text-ink">
                  {value === null || value === undefined
                    ? t.settings.notSet
                    : String(value)}
                </span>
              </div>
            ))}
            {entries.length === 0 && !loading && (
              <p className="py-4 text-center text-sm text-faint">
                {t.common.noData}
              </p>
            )}
          </div>
        )}
      </Card>

      <p className="flex items-center gap-2 text-xs text-faint">
        <SettingsIcon size={14} />
        {t.settings.storedLocally}
      </p>
    </div>
  );
}

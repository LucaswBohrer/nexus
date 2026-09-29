"use client";

import { useEffect, useState } from "react";
import { Pencil, Settings2, X } from "lucide-react";

import { ApiError, getSettings, updateSetting } from "../../lib/api";
import { ALL_METRICS, usePreferences } from "../../lib/preferences";
import type { SettingValue } from "../../types/monitoring";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

type InputKind = "decimal" | "integer" | "nullable-decimal";

interface FieldDef {
  key: string;
  unit?: string;
  kind: InputKind;
}

interface FieldView extends FieldDef {
  label: string;
  description: string;
}

// Metadados de apresentação por chave do backend (rótulos e descrições
// vivem no dicionário i18n; aqui ficam só unidade e tipo de entrada).
const SECTION_FIELDS: { section: string; hint: string; fields: FieldDef[] }[] = [
  {
    section: "thresholds",
    hint: "thresholdsHint",
    fields: [
      { key: "thresholds.voltage_min", unit: "V", kind: "decimal" },
      { key: "thresholds.voltage_max", unit: "V", kind: "decimal" },
      { key: "thresholds.frequency_min", unit: "Hz", kind: "decimal" },
      { key: "thresholds.frequency_max", unit: "Hz", kind: "decimal" },
      { key: "thresholds.power_factor_min", kind: "decimal" },
      { key: "thresholds.temperature_max", unit: "°C", kind: "decimal" },
    ],
  },
  {
    section: "energy",
    hint: "energyHint",
    fields: [{ key: "energy_tariff", unit: "R$/kWh", kind: "nullable-decimal" }],
  },
  {
    section: "retention",
    hint: "retentionHint",
    fields: [
      { key: "retention.readings_days", unit: "dias", kind: "integer" },
      { key: "retention.events_days", unit: "dias", kind: "integer" },
      {
        key: "retention.diagnostic_episodes_days",
        unit: "dias",
        kind: "integer",
      },
      {
        key: "retention.simulation_sessions_days",
        unit: "dias",
        kind: "integer",
      },
    ],
  },
  {
    section: "simulation",
    hint: "simulationHint",
    fields: [
      { key: "simulation.default_intensity", kind: "integer" },
      {
        key: "simulation.default_duration_minutes",
        unit: "min",
        kind: "nullable-decimal",
      },
    ],
  },
];

function formatValue(
  value: SettingValue,
  field: FieldDef,
  notSet: string
): string {
  if (value === null || value === undefined) {
    return notSet;
  }
  const num = Number(value);
  const text = Number.isFinite(num) ? String(num) : String(value);
  return field.unit ? `${text} ${field.unit}` : text;
}

function SettingRow({
  field,
  value,
  onSaved,
}: {
  field: FieldView;
  value: SettingValue;
  onSaved: (key: string, value: SettingValue) => void;
}) {
  const { t } = usePreferences();
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setInput(value === null || value === undefined ? "" : String(value));
    setError(null);
    setEditing(true);
  }

  async function save() {
    setError(null);
    let parsed: SettingValue;
    const trimmed = input.trim();
    if (trimmed === "" && field.kind === "nullable-decimal") {
      parsed = null;
    } else {
      const num = Number(trimmed.replace(",", "."));
      if (!Number.isFinite(num)) {
        setError(t.common.invalidValue);
        return;
      }
      parsed = field.kind === "integer" ? Math.round(num) : num;
    }
    setSaving(true);
    try {
      const saved = await updateSetting(field.key, parsed);
      onSaved(field.key, saved as SettingValue);
      setEditing(false);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setError(t.common.unauthorized);
      } else {
        setError(err instanceof Error ? err.message : t.common.invalidValue);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl bg-surface-2 px-4 py-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{field.label}</p>
        <p className="mt-0.5 text-xs text-muted">{field.description}</p>
      </div>
      {editing ? (
        <div className="flex flex-col gap-2 sm:items-end">
          <div className="flex items-center gap-2">
            <input
              type="text"
              inputMode="decimal"
              className="field w-36"
              value={input}
              placeholder={
                field.kind === "nullable-decimal"
                  ? t.settings.emptyMeansUnset
                  : ""
              }
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  void save();
                }
                if (e.key === "Escape") {
                  setEditing(false);
                }
              }}
              autoFocus
            />
            {field.unit && (
              <span className="text-xs text-faint">{field.unit}</span>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="flex min-h-[44px] items-center gap-1 rounded-xl px-3 text-xs font-medium text-muted"
            >
              <X size={14} />
              {t.common.cancel}
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="min-h-[44px] rounded-xl bg-[var(--info)] px-4 text-xs font-medium text-white disabled:opacity-60"
            >
              {saving ? t.common.saving : t.common.save}
            </button>
          </div>
          {error && <p className="text-xs text-[var(--bad)]">{error}</p>}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">
            {formatValue(value, field, t.settings.notSet)}
          </span>
          <button
            type="button"
            onClick={startEditing}
            aria-label={`${t.common.edit}: ${field.label}`}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-muted hover:bg-surface-3"
          >
            <Pencil size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { t, preferences, updatePreferences } = usePreferences();

  const [settings, setSettings] = useState<Record<string, SettingValue> | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await getSettings();
        if (!cancelled) {
          setSettings(response.settings as Record<string, SettingValue>);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t.common.connectionError
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  function handleSaved(key: string, value: SettingValue) {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  const pref = preferences;

  return (
    <div className="space-y-5">
      <PageHeader title={t.settings.title} subtitle={t.settings.subtitle} />

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorBanner message={error} />
      ) : settings ? (
        <>
          {SECTION_FIELDS.map((section) => {
            const labels = t.settings.labels as Record<string, string>;
            const descriptions = t.settings.descriptions as Record<
              string,
              string
            >;
            const sections = t.settings.sections as Record<string, string>;
            const hints = {
              thresholdsHint: t.settings.thresholdsHint,
              energyHint: t.settings.energyHint,
              retentionHint: t.settings.retentionHint,
              simulationHint: t.settings.simulationHint,
            } as Record<string, string>;
            const title = sections[section.section] ?? section.section;
            return (
              <Card key={section.section}>
                <CardHeader eyebrow={title} title={title} />
                <p className="mt-1 text-xs text-faint">
                  {hints[section.hint] ?? ""}
                </p>
                <div className="mt-4 space-y-2">
                  {section.fields.map((def) => (
                    <SettingRow
                      key={def.key}
                      field={{
                        ...def,
                        label: labels[def.key] ?? def.key,
                        description: descriptions[def.key] ?? "",
                      }}
                      value={settings[def.key]}
                      onSaved={handleSaved}
                    />
                  ))}
                </div>
              </Card>
            );
          })}
        </>
      ) : (
        <Card>
          <EmptyState
            icon={Settings2}
            title={t.common.noData}
            message={t.common.connectionError}
          />
        </Card>
      )}

      {/* PREFERÊNCIAS DE EXIBIÇÃO — só localStorage, nunca o backend */}
      <Card>
        <CardHeader
          eyebrow={t.settings.displayPrefs}
          title={t.settings.displayPrefs}
        />
        <p className="mt-1 text-xs text-faint">{t.settings.displayPrefsHint}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.theme}
            </span>
            <select
              className="field"
              value={pref.theme}
              onChange={(e) =>
                updatePreferences({ theme: e.target.value as "light" | "dark" })
              }
            >
              <option value="light">{t.settings.themeLight}</option>
              <option value="dark">{t.settings.themeDark}</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.language}
            </span>
            <select
              className="field"
              value={pref.language}
              onChange={(e) =>
                updatePreferences({ language: e.target.value as "pt-BR" })
              }
            >
              <option value="pt-BR">Português (Brasil)</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.dateFormat}
            </span>
            <select
              className="field"
              value={pref.datetimeFormat}
              onChange={(e) =>
                updatePreferences({
                  datetimeFormat: e.target.value as "local" | "iso",
                })
              }
            >
              <option value="local">{t.settings.prefs.datetimeLocal}</option>
              <option value="iso">{t.settings.prefs.datetimeIso}</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.defaultRange}
            </span>
            <select
              className="field"
              value={pref.defaultRange}
              onChange={(e) =>
                updatePreferences({
                  defaultRange: e.target.value as
                    | "1h"
                    | "6h"
                    | "24h"
                    | "7d",
                })
              }
            >
              <option value="1h">1h</option>
              <option value="6h">6h</option>
              <option value="24h">24h</option>
              <option value="7d">7d</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.density}
            </span>
            <select
              className="field"
              value={pref.density}
              onChange={(e) =>
                updatePreferences({
                  density: e.target.value as "comfortable" | "compact",
                })
              }
            >
              <option value="comfortable">{t.settings.densityComfortable}</option>
              <option value="compact">{t.settings.densityCompact}</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.settings.polling}
            </span>
            <select
              className="field"
              value={String(pref.pollingIntervalMs)}
              onChange={(e) =>
                updatePreferences({ pollingIntervalMs: Number(e.target.value) })
              }
            >
              <option value="0">{t.settings.prefs.pollingOff}</option>
              <option value="2000">{t.settings.polling2s}</option>
              <option value="5000">{t.settings.polling5s}</option>
              <option value="10000">{t.settings.polling10s}</option>
              <option value="30000">{t.settings.polling30s}</option>
            </select>
          </label>
        </div>

        <div className="mt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-faint">
            {t.settings.prefs.favoriteMetrics}
          </p>
          <div className="flex flex-wrap gap-2">
            {ALL_METRICS.map((metric) => {
              const active = pref.favoriteMetrics.includes(metric);
              return (
                <button
                  key={metric}
                  type="button"
                  onClick={() =>
                    updatePreferences({
                      favoriteMetrics: active
                        ? pref.favoriteMetrics.filter((m) => m !== metric)
                        : [...pref.favoriteMetrics, metric],
                    })
                  }
                  aria-pressed={active}
                  className={`min-h-[44px] rounded-xl px-4 text-xs font-medium transition ${
                    active
                      ? "bg-[var(--info)] text-white"
                      : "bg-surface-2 text-muted"
                  }`}
                >
                  {metric}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-faint">
            {t.settings.prefs.favoriteMetricsHint}
          </p>
        </div>
      </Card>
    </div>
  );
}

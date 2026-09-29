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
  label: string;
  description: string;
  unit?: string;
  kind: InputKind;
  step?: string;
}

interface SectionDef {
  title: string;
  subtitle: string;
  fields: FieldDef[];
}

const SECTIONS: SectionDef[] = [
  {
    title: "Limites de alerta",
    subtitle:
      "Aplicados pelo backend ao diagnóstico em tempo real. Alterações valem sem reiniciar.",
    fields: [
      {
        key: "thresholds.voltage_min",
        label: "Tensão mínima",
        description: "Abaixo disso o backend gera evento de subtensão.",
        unit: "V",
        kind: "decimal",
        step: "0.1",
      },
      {
        key: "thresholds.voltage_max",
        label: "Tensão máxima",
        description: "Acima disso o backend gera evento de sobretensão.",
        unit: "V",
        kind: "decimal",
        step: "0.1",
      },
      {
        key: "thresholds.frequency_min",
        label: "Frequência mínima",
        description: "Abaixo disso o backend gera evento de frequência.",
        unit: "Hz",
        kind: "decimal",
        step: "0.1",
      },
      {
        key: "thresholds.frequency_max",
        label: "Frequência máxima",
        description: "Acima disso o backend gera evento de frequência.",
        unit: "Hz",
        kind: "decimal",
        step: "0.1",
      },
      {
        key: "thresholds.power_factor_min",
        label: "Fator de potência mínimo",
        description: "Abaixo disso o backend gera evento de baixo fator de potência.",
        kind: "decimal",
        step: "0.01",
      },
      {
        key: "thresholds.temperature_max",
        label: "Temperatura máxima",
        description: "Acima disso o backend gera evento de temperatura.",
        unit: "°C",
        kind: "decimal",
        step: "0.5",
      },
    ],
  },
  {
    title: "Energia",
    subtitle: "Parâmetros usados no cálculo de custo da energia.",
    fields: [
      {
        key: "energy_tariff",
        label: "Tarifa de energia",
        description:
          "Valor do kWh para estimativa de custo. Deixe vazio se desconhecido.",
        unit: "R$/kWh",
        kind: "nullable-decimal",
        step: "0.001",
      },
    ],
  },
  {
    title: "Retenção de dados",
    subtitle: "Por quanto tempo o backend guarda cada tipo de registro.",
    fields: [
      {
        key: "retention.readings_days",
        label: "Leituras",
        description: "Dias de telemetria bruta mantidos no banco.",
        unit: "dias",
        kind: "integer",
        step: "1",
      },
      {
        key: "retention.events_days",
        label: "Eventos",
        description: "Dias de eventos mantidos no banco.",
        unit: "dias",
        kind: "integer",
        step: "1",
      },
      {
        key: "retention.diagnostic_episodes_days",
        label: "Episódios diagnósticos",
        description: "Dias de episódios diagnósticos mantidos no banco.",
        unit: "dias",
        kind: "integer",
        step: "1",
      },
      {
        key: "retention.simulation_sessions_days",
        label: "Sessões de simulação",
        description: "Dias de sessões de simulação mantidos no banco.",
        unit: "dias",
        kind: "integer",
        step: "1",
      },
    ],
  },
  {
    title: "Simulação",
    subtitle: "Valores padrão usados ao iniciar uma simulação.",
    fields: [
      {
        key: "simulation.default_intensity",
        label: "Intensidade padrão",
        description: "Intensidade inicial das sessões de simulação (0–200).",
        kind: "integer",
        step: "1",
      },
      {
        key: "simulation.default_duration_minutes",
        label: "Duração padrão",
        description:
          "Duração inicial em minutos. Vazio significa sem limite.",
        unit: "min",
        kind: "nullable-decimal",
        step: "1",
      },
    ],
  },
];

function formatValue(value: SettingValue, def: FieldDef): string {
  if (value === null || value === undefined) {
    return "Não definido";
  }
  const num = Number(value);
  const text = Number.isFinite(num) ? String(num) : String(value);
  return def.unit ? `${text} ${def.unit}` : text;
}

function SettingRow({
  def,
  value,
  onSaved,
}: {
  def: FieldDef;
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
    if (trimmed === "" && def.kind === "nullable-decimal") {
      parsed = null;
    } else {
      const num = Number(trimmed.replace(",", "."));
      if (!Number.isFinite(num)) {
        setError(t.common.invalidValue);
        return;
      }
      parsed = def.kind === "integer" ? Math.round(num) : num;
    }
    setSaving(true);
    try {
      const saved = await updateSetting(def.key, parsed);
      onSaved(def.key, saved as SettingValue);
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
        <p className="text-sm font-medium text-ink">{def.label}</p>
        <p className="mt-0.5 text-xs text-muted">{def.description}</p>
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
                def.kind === "nullable-decimal" ? "Vazio = não definido" : ""
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
            {def.unit && (
              <span className="text-xs text-faint">{def.unit}</span>
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
            {formatValue(value, def)}
          </span>
          <button
            type="button"
            onClick={startEditing}
            aria-label={`Editar: ${def.label}`}
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
          {SECTIONS.map((section) => (
            <Card key={section.title}>
              <CardHeader
                eyebrow={section.title}
                title={section.title}
              />
              <p className="mt-1 text-xs text-faint">{section.subtitle}</p>
              <div className="mt-4 space-y-2">
                {section.fields.map((def) => (
                  <SettingRow
                    key={def.key}
                    def={def}
                    value={settings[def.key]}
                    onSaved={handleSaved}
                  />
                ))}
              </div>
            </Card>
          ))}
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

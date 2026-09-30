"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Bell,
  FileText,
  FlaskConical,
  Gauge,
  History,
  Radio,
  Server,
  Stethoscope,
  TriangleAlert,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { getEpisodes, getEquipment, getEquipmentSummary, getEventsV1 } from "../../../lib/api";
import { useEquipment } from "../../../lib/equipment";
import { usePreferences } from "../../../lib/preferences";
import { formatDateTime, formatNumber } from "../../../lib/format";
import type {
  DiagnosticEpisode,
  Equipment,
  EquipmentStatus,
  EquipmentSummary,
  V1Event,
} from "../../../types/monitoring";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../../components/ui";

function statusTone(status: EquipmentStatus): string {
  switch (status) {
    case "active":
      return "normal";
    case "maintenance":
      return "warning";
    default:
      return "neutral";
  }
}

function QuickLink({
  href,
  label,
  icon: Icon,
  equipmentId,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  equipmentId: number;
}) {
  const router = useRouter();
  const { select } = useEquipment();
  const target = href.includes("?")
    ? `${href}&equipment_id=${equipmentId}`
    : `${href}?equipment_id=${equipmentId}`;
  return (
    <button
      type="button"
      onClick={() => {
        // O destino abre já com este equipamento selecionado; a query
        // garante o deep link mesmo após refresh.
        select(equipmentId);
        router.push(target);
      }}
      className="flex min-h-[52px] items-center gap-3 rounded-2xl bg-surface-2 px-4 text-left transition hover:bg-surface-3"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-3 text-muted">
        <Icon size={17} />
      </span>
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
        {label}
      </span>
      <ArrowRight size={15} className="shrink-0 text-faint" />
    </button>
  );
}

function ReadingGrid({ summary }: { summary: EquipmentSummary }) {
  const { t, preferences } = usePreferences();
  const r = summary.last_reading;
  if (!r) {
    return (
      <p className="py-6 text-center text-sm text-faint">
        {t.equipment.noLastReading}
      </p>
    );
  }
  const items: { label: string; value: string }[] = [
    { label: t.dashboard.voltage, value: `${formatNumber(r.voltage, 1)} V` },
    { label: t.dashboard.current, value: `${formatNumber(r.current, 1)} A` },
    {
      label: t.dashboard.activePower,
      value: `${formatNumber(r.active_power, 2)} kW`,
    },
    {
      label: t.dashboard.powerFactor,
      value: formatNumber(r.power_factor, 3),
    },
    {
      label: t.dashboard.temperature,
      value: `${formatNumber(r.temperature, 1)} °C`,
    },
    {
      label: t.dashboard.frequency,
      value: `${formatNumber(r.frequency, 2)} Hz`,
    },
  ];
  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl bg-surface-2 px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-faint">
              {item.label}
            </p>
            <p className="mt-1 text-lg font-semibold text-ink">{item.value}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-faint">
        {t.common.lastUpdate}: {formatDateTime(r.timestamp, preferences)}
      </p>
    </>
  );
}

export default function EquipmentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const equipmentId = Number(id);
  const { t, preferences } = usePreferences();
  const { select, equipmentId: selectedId } = useEquipment();

  const [equipment, setEquipment] = useState<Equipment | null>(null);
  const [summary, setSummary] = useState<EquipmentSummary | null>(null);
  const [events, setEvents] = useState<V1Event[]>([]);
  const [episodes, setEpisodes] = useState<DiagnosticEpisode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!Number.isFinite(equipmentId) || equipmentId <= 0) {
        setError(t.equipment.loadError);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const [eq, sum, openEvents, ackEvents, eps] = await Promise.all([
          getEquipment(equipmentId),
          getEquipmentSummary(equipmentId),
          getEventsV1({ status: "open", limit: 5, equipment_id: equipmentId }),
          getEventsV1({
            status: "acknowledged",
            limit: 5,
            equipment_id: equipmentId,
          }),
          getEpisodes(20, equipmentId),
        ]);
        if (!cancelled) {
          setEquipment(eq);
          setSummary(sum);
          const merged = new Map<number, V1Event>();
          for (const e of [...openEvents.events, ...ackEvents.events]) {
            merged.set(e.id, e);
          }
          setEvents(
            [...merged.values()].sort((a, b) => b.id - a.id).slice(0, 5)
          );
          setEpisodes(eps.filter((ep) => ep.status === "open").slice(0, 5));
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t.equipment.summaryError
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [equipmentId, reloadKey, t]);

  const isCurrent = selectedId === equipmentId;
  const diagnosis = summary?.diagnosis;

  const quickLinks: { href: string; label: string; icon: LucideIcon }[] = [
    { href: "/monitor", label: t.nav.monitor, icon: Radio },
    { href: "/history", label: t.nav.history, icon: History },
    { href: "/events", label: t.nav.events, icon: Bell },
    { href: "/diagnostics", label: t.nav.diagnostics, icon: Stethoscope },
    { href: "/analytics", label: t.nav.analytics, icon: BarChart3 },
    { href: "/simulation", label: t.nav.simulation, icon: FlaskConical },
    { href: "/reports", label: t.nav.reports, icon: FileText },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={equipment?.name ?? t.equipment.details}
        subtitle={
          equipment
            ? `${equipment.code}${equipment.location ? ` · ${equipment.location}` : ""}`
            : t.equipment.subtitle
        }
        actions={
          equipment ? (
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={statusTone(equipment.status)}>
                {t.equipment.statuses[equipment.status] ?? equipment.status}
              </Badge>
              <Badge tone={equipment.enabled ? "normal" : "neutral"}>
                {equipment.enabled
                  ? t.equipment.enabled
                  : t.equipment.disabled}
              </Badge>
              {equipment.code === "DEFAULT" && (
                <Badge tone="info">{t.equipment.defaultBadge}</Badge>
              )}
            </div>
          ) : undefined
        }
      />

      {error && (
        <ErrorBanner
          message={error}
          onRetry={() => {
            setReloadKey((k) => k + 1);
          }}
        />
      )}

      {loading ? (
        <LoadingState />
      ) : equipment && summary ? (
        <>
          {!isCurrent && (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted">{t.equipment.selectHint}</p>
                <button
                  type="button"
                  onClick={() => select(equipment.id)}
                  className="flex min-h-[44px] items-center gap-2 rounded-xl bg-[var(--info)] px-4 text-sm font-semibold text-white"
                >
                  <Activity size={16} />
                  {t.equipment.select}
                </button>
              </div>
            </Card>
          )}

          {/* IDENTIDADE */}
          <Card>
            <CardHeader
              eyebrow={t.equipment.details}
              title={equipment.name}
            />
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-xs text-faint">{t.equipment.code}</dt>
                <dd className="mt-1 font-medium text-ink">{equipment.code}</dd>
              </div>
              <div>
                <dt className="text-xs text-faint">{t.equipment.type}</dt>
                <dd className="mt-1 font-medium text-ink">
                  {equipment.equipment_type ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-faint">{t.equipment.location}</dt>
                <dd className="mt-1 font-medium text-ink">
                  {equipment.location ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-faint">{t.equipment.readingsCount}</dt>
                <dd className="mt-1 font-medium text-ink">
                  {formatNumber(summary.readings_count, 0)}
                </dd>
              </div>
            </dl>
            {equipment.description && (
              <p className="mt-3 text-sm text-muted">{equipment.description}</p>
            )}
            {!equipment.enabled && (
              <p className="mt-3 rounded-xl bg-surface-2 px-4 py-2.5 text-xs text-[var(--warn)]">
                {t.equipment.writeBlocked}
              </p>
            )}
          </Card>

          {/* ÚLTIMA LEITURA */}
          <Card>
            <CardHeader
              eyebrow={t.equipment.lastReading}
              title={t.equipment.lastReading}
              action={<Gauge size={18} className="text-faint" />}
            />
            <div className="mt-4">
              <ReadingGrid summary={summary} />
            </div>
          </Card>

          {/* DIAGNÓSTICO */}
          <Card>
            <CardHeader
              eyebrow={t.equipment.diagnosis}
              title={t.equipment.diagnosis}
              action={
                diagnosis ? (
                  <Badge tone={diagnosis.severity}>
                    {t.status[diagnosis.severity]}
                  </Badge>
                ) : undefined
              }
            />
            {!diagnosis ? (
              <p className="mt-4 text-sm text-faint">
                {t.equipment.noLastReading}
              </p>
            ) : diagnosis.anomalies.length === 0 ? (
              <p className="mt-4 text-sm text-muted">
                {t.dashboard.noAnomalies}
              </p>
            ) : (
              <div className="mt-4 space-y-2">
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
                  <div className="pt-1">
                    <p className="mb-1 text-xs font-medium uppercase tracking-wider text-faint">
                      {t.dashboard.recommendations}
                    </p>
                    {diagnosis.recommendations.map((rec, i) => (
                      <p key={i} className="text-sm text-muted">
                        • {rec}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* EVENTOS ATIVOS + EPISÓDIOS */}
          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader
                eyebrow={t.equipment.activeEvents}
                title={`${t.equipment.activeEvents} · ${summary.active_events}`}
                action={
                  <Link
                    href={`/events?equipment_id=${equipment.id}`}
                    onClick={() => select(equipment.id)}
                    className="flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-xs font-medium text-[var(--info)]"
                  >
                    {t.common.viewAll}
                    <ArrowRight size={14} />
                  </Link>
                }
              />
              <div className="mt-4 space-y-2">
                {events.length === 0 ? (
                  <p className="py-4 text-center text-sm text-faint">
                    {t.dashboard.noActiveEvents}
                  </p>
                ) : (
                  events.map((event) => (
                    <div
                      key={event.id}
                      className="flex items-center gap-3 rounded-xl bg-surface-2 px-4 py-3"
                    >
                      <Bell size={15} className="shrink-0 text-[var(--warn)]" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          {event.event_type}
                        </p>
                        <p className="truncate text-xs text-muted">
                          {event.message}
                        </p>
                      </div>
                      <Badge tone={event.severity}>
                        {t.status[event.severity]}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <Card>
              <CardHeader
                eyebrow={t.equipment.openEpisodes}
                title={`${t.equipment.openEpisodes} · ${summary.open_episodes}`}
                action={
                  <Link
                    href={`/diagnostics?equipment_id=${equipment.id}`}
                    onClick={() => select(equipment.id)}
                    className="flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-xs font-medium text-[var(--info)]"
                  >
                    {t.common.viewAll}
                    <ArrowRight size={14} />
                  </Link>
                }
              />
              <div className="mt-4 space-y-2">
                {episodes.length === 0 ? (
                  <EmptyState
                    icon={Stethoscope}
                    title={t.diagnostics.noEpisodes}
                    message=""
                  />
                ) : (
                  episodes.map((ep) => (
                    <div
                      key={ep.id}
                      className="flex items-center gap-3 rounded-xl bg-surface-2 px-4 py-3"
                    >
                      <Waves size={15} className="shrink-0 text-[var(--warn)]" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          #{ep.id} · {ep.rules.join(", ")}
                        </p>
                        <p className="truncate text-xs text-muted">
                          {t.diagnostics.startedAt}:{" "}
                          {formatDateTime(ep.started_at, preferences)}
                        </p>
                      </div>
                      <Badge tone={ep.severity}>
                        {t.status[ep.severity]}
                      </Badge>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          {/* ACESSO RÁPIDO */}
          <Card>
            <CardHeader
              eyebrow={t.equipment.quickLinks}
              title={t.equipment.quickLinks}
              action={<Zap size={18} className="text-faint" />}
            />
            <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {quickLinks.map((link) => (
                <QuickLink
                  key={link.href}
                  href={link.href}
                  label={link.label}
                  icon={link.icon}
                  equipmentId={equipment.id}
                />
              ))}
            </div>
          </Card>

          {/* Voltar */}
          <Link
            href="/equipment"
            className="flex min-h-[44px] items-center gap-2 text-sm font-medium text-[var(--info)]"
          >
            <Server size={15} />
            {t.equipment.title}
          </Link>
        </>
      ) : null}
    </div>
  );
}

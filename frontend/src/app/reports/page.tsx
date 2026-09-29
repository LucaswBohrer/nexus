"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CalendarDays,
  Download,
  FileJson,
  FileSpreadsheet,
  FileText,
  Loader2,
} from "lucide-react";

import {
  downloadReport,
  getReportSummary,
  type ReportKind,
} from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import { errorMessage } from "../../lib/usePoll";
import type { ReportSummary } from "../../types/monitoring";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

type PeriodType = "daily" | "weekly" | "custom";

function utcToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function currentIsoWeek(): string {
  const now = new Date();
  const d = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  );
  const day = (d.getUTCDay() + 6) % 7; // Mon = 0
  d.setUTCDate(d.getUTCDate() - day + 3); // Thursday
  const isoYear = d.getUTCFullYear();
  const jan4 = new Date(Date.UTC(isoYear, 0, 4));
  const jan4Day = (jan4.getUTCDay() + 6) % 7;
  const week1Monday = new Date(Date.UTC(isoYear, 0, 4 - jan4Day));
  const week = Math.round((d.getTime() - week1Monday.getTime()) / 604800000) + 1;
  return `${isoYear}-W${String(week).padStart(2, "0")}`;
}

function filenameSlug(value: string): string {
  return value.replace(/[^0-9A-Za-z_-]+/g, "-");
}

export default function ReportsPage() {
  const { t, preferences } = usePreferences();

  const [periodType, setPeriodType] = useState<PeriodType>("daily");
  const [date, setDate] = useState(utcToday());
  const [week, setWeek] = useState(currentIsoWeek());
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const [data, setData] = useState<ReportSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const summaryKind: ReportKind =
    periodType === "custom" ? "summary" : periodType;

  const summaryParams = useCallback((): Record<string, string> => {
    if (periodType === "daily") return { date };
    if (periodType === "weekly") return { week };
    return {
      from: new Date(customFrom).toISOString(),
      to: new Date(customTo).toISOString(),
    };
  }, [periodType, date, week, customFrom, customTo]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const summary = await getReportSummary(summaryKind, summaryParams());
      setData(summary);
    } catch (err) {
      setError(errorMessage(err, t.reports.summaryError));
    } finally {
      setLoading(false);
    }
  }, [summaryKind, summaryParams, t]);

  // Carrega o resumo inicial (hoje).
  useEffect(() => {
    function initialLoad() {
      void load();
    }
    initialLoad();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const periodLabel =
    periodType === "daily"
      ? date
      : periodType === "weekly"
        ? week
        : `${customFrom || "…"} → ${customTo || "…"}`;

  async function handleExport(
    key: string,
    kind: ReportKind,
    params: Record<string, string>,
    filename: string
  ) {
    if (exporting) return;
    setExporting(key);
    setExportError(null);
    try {
      await downloadReport(kind, params, filename);
    } catch (err) {
      setExportError(errorMessage(err, t.reports.exportError));
    } finally {
      setExporting(null);
    }
  }

  const slug = data ? filenameSlug(data.period.from.slice(0, 10)) : "periodo";
  const exportReadings = () =>
    handleExport(
      "readings",
      summaryKind,
      { ...summaryParams(), format: "csv" },
      `nexus-readings-${slug}.csv`
    );
  const exportEvents = () =>
    data &&
    handleExport(
      "events",
      "events",
      { from: data.period.from, to: data.period.to, format: "csv" },
      `nexus-events-${slug}.csv`
    );
  const exportJson = () =>
    handleExport(
      "json",
      summaryKind,
      { ...summaryParams(), format: "json" },
      `nexus-summary-${slug}.json`
    );

  const summary = data?.summary;

  return (
    <div className="space-y-5">
      <PageHeader title={t.reports.title} subtitle={t.reports.subtitle} />

      {exportError && <ErrorBanner message={exportError} />}

      {/* --- Período --- */}
      <Card>
        <CardHeader eyebrow={t.reports.periodLabel} title={periodLabel} />
        <div className="mt-4 flex flex-wrap gap-2">
          {(
            [
              ["daily", t.reports.periodDaily],
              ["weekly", t.reports.periodWeekly],
              ["custom", t.reports.periodCustom],
            ] as [PeriodType, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setPeriodType(value)}
              aria-pressed={periodType === value}
              className={`min-h-[44px] rounded-xl px-4 py-2 text-sm font-medium transition ${
                periodType === value
                  ? "bg-[var(--info)] text-white"
                  : "bg-surface-3 text-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          {periodType === "daily" && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-faint">{t.reports.dateLabel}</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="h-11 rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink"
              />
            </label>
          )}
          {periodType === "weekly" && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-faint">{t.reports.weekLabel}</span>
              <input
                type="week"
                value={week}
                onChange={(e) => setWeek(e.target.value)}
                className="h-11 rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink"
              />
            </label>
          )}
          {periodType === "custom" && (
            <>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs text-faint">{t.reports.fromLabel}</span>
                <input
                  type="datetime-local"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  className="h-11 rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs text-faint">{t.reports.toLabel}</span>
                <input
                  type="datetime-local"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  className="h-11 rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink"
                />
              </label>
            </>
          )}
          <button
            type="button"
            onClick={() => void load()}
            disabled={
              loading || (periodType === "custom" && (!customFrom || !customTo))
            }
            className="flex min-h-[44px] items-center gap-2 rounded-xl bg-[var(--info)] px-5 text-sm font-semibold text-white transition disabled:opacity-60"
          >
            {loading && <Loader2 size={16} className="animate-spin" />}
            {t.reports.loadSummary}
          </button>
        </div>
      </Card>

      {/* --- Resumo --- */}
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {loading ? (
        <Card>
          <LoadingState />
        </Card>
      ) : data && summary ? (
        <>
          {summary.readings_count === 0 ? (
            <Card>
              <EmptyState
                icon={CalendarDays}
                title={t.reports.summaryTitle}
                message={t.reports.emptyPeriod}
              />
            </Card>
          ) : (
            <Card>
              <CardHeader
                eyebrow={t.reports.summaryTitle}
                title={`${formatDateTime(data.period.from, preferences)} → ${formatDateTime(data.period.to, preferences)}`}
              />
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <SummaryItem label={t.reports.energy} value={`${formatNumber(summary.energy_kwh, 3)} kWh`} />
                <SummaryItem label={t.reports.readings} value={formatNumber(summary.readings_count, 0)} />
                <SummaryItem label={t.reports.powerAvg} value={`${formatNumber(summary.power_avg, 2)} kW`} />
                <SummaryItem label={t.reports.powerMax} value={`${formatNumber(summary.power_max, 2)} kW`} />
                <SummaryItem label={t.reports.voltageAvg} value={`${formatNumber(summary.voltage_avg, 1)} V`} />
                <SummaryItem
                  label={t.reports.voltageRange}
                  value={`${formatNumber(summary.voltage_min, 1)} / ${formatNumber(summary.voltage_max, 1)} V`}
                />
                <SummaryItem label={t.reports.powerFactorAvg} value={formatNumber(summary.power_factor_avg, 3)} />
                <SummaryItem label={t.reports.tempMax} value={`${formatNumber(summary.temperature_max, 1)} °C`} />
              </dl>

              <div className="mt-5 grid gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-faint">
                    {t.reports.statusTitle}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone="normal">normal · {data.status.normal}</Badge>
                    <Badge tone="warning">warning · {data.status.warning}</Badge>
                    <Badge tone="critical">critical · {data.status.critical}</Badge>
                  </div>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-faint">
                    {t.reports.eventsTitle} · {data.events.length}
                  </p>
                  <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-muted">
                    {data.events.slice(0, 10).map((e) => (
                      <li key={e.id} className="truncate">
                        {formatDateTime(e.opened_at ?? e.timestamp, preferences)} —{" "}
                        {e.message}
                      </li>
                    ))}
                    {data.events.length === 0 && <li>{t.reports.emptyPeriod}</li>}
                  </ul>
                  {data.events_truncated && (
                    <p className="mt-1 text-xs text-faint">
                      {t.reports.eventsTruncated}
                    </p>
                  )}
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-faint">
                    {t.reports.episodesTitle} · {data.diagnostic_episodes.length}
                  </p>
                  <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-muted">
                    {data.diagnostic_episodes.slice(0, 10).map((ep) => (
                      <li key={ep.id} className="truncate">
                        {formatDateTime(ep.started_at, preferences)} —{" "}
                        {ep.severity}
                      </li>
                    ))}
                    {data.diagnostic_episodes.length === 0 && (
                      <li>{t.reports.emptyPeriod}</li>
                    )}
                  </ul>
                </div>
              </div>
            </Card>
          )}

          {/* --- Exportação --- */}
          <Card>
            <CardHeader
              eyebrow={t.reports.exportTitle}
              title={t.reports.exportTitle}
            />
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <ExportButton
                busy={exporting === "readings"}
                onClick={exportReadings}
                icon={FileSpreadsheet}
                label={t.reports.exportReadingsCsv}
              />
              <ExportButton
                busy={exporting === "events"}
                onClick={exportEvents}
                icon={FileText}
                label={t.reports.exportEventsCsv}
              />
              <ExportButton
                busy={exporting === "json"}
                onClick={exportJson}
                icon={FileJson}
                label={t.reports.exportJson}
              />
            </div>
            <p className="mt-3 text-xs text-faint">{t.reports.note}</p>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-1 font-medium text-ink">{value}</dd>
    </div>
  );
}

function ExportButton({
  busy,
  onClick,
  icon: Icon,
  label,
}: {
  busy: boolean;
  onClick: () => void;
  icon: typeof Download;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="flex min-h-[52px] flex-1 items-center justify-center gap-2 rounded-2xl bg-[var(--info)] px-6 text-sm font-semibold text-white transition disabled:cursor-wait disabled:opacity-60"
    >
      {busy ? <Loader2 size={18} className="animate-spin" /> : <Icon size={18} />}
      {label}
    </button>
  );
}

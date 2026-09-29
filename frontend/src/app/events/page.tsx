"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, Check, Search } from "lucide-react";

import { ApiError, getEventsV1, patchEvent } from "../../lib/api";
import { formatDateTime, formatNumber } from "../../lib/format";
import { usePreferences } from "../../lib/preferences";
import type {
  EventStatus,
  NormalizedSeverity,
  V1Event,
} from "../../types/monitoring";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

type Tab = "active" | "all" | "resolved";

const TAB_STATUSES: Record<Tab, EventStatus[]> = {
  active: ["open", "acknowledged"],
  all: [],
  resolved: ["resolved"],
};

const KNOWN_TYPES = [
  "HIGH_VOLTAGE",
  "LOW_VOLTAGE",
  "FREQUENCY_OUT_OF_RANGE",
  "LOW_POWER_FACTOR",
  "HIGH_TEMPERATURE",
];

interface Filters {
  severity: "" | NormalizedSeverity;
  type: string;
  from: string;
  to: string;
  q: string;
}

const EMPTY_FILTERS: Filters = {
  severity: "",
  type: "",
  from: "",
  to: "",
  q: "",
};

function toIso(local: string): string | undefined {
  if (!local) {
    return undefined;
  }
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

function mergeById(lists: V1Event[][]): V1Event[] {
  const map = new Map<number, V1Event>();
  for (const list of lists) {
    for (const e of list) {
      map.set(e.id, e);
    }
  }
  return [...map.values()].sort((a, b) => b.id - a.id);
}

export default function EventsPage() {
  const { t, preferences } = usePreferences();

  const [tab, setTab] = useState<Tab>("active");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [qInput, setQInput] = useState("");

  const [items, setItems] = useState<V1Event[]>([]);
  const [cursors, setCursors] = useState<(number | null)[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState<number | null>(null);

  const statuses = TAB_STATUSES[tab];

  // Debounce da busca textual.
  useEffect(() => {
    const id = setTimeout(() => {
      setFilters((f) => (f.q === qInput ? f : { ...f, q: qInput }));
    }, 500);
    return () => clearTimeout(id);
  }, [qInput]);

  const queryKey = useMemo(
    () =>
      JSON.stringify({
        tab,
        severity: filters.severity,
        type: filters.type,
        from: filters.from,
        to: filters.to,
        q: filters.q,
      }),
    [tab, filters]
  );

  const fetchPage = useCallback(
    async (status: EventStatus | undefined, cursor?: number) => {
      return getEventsV1({
        status,
        severity: filters.severity || undefined,
        type: filters.type || undefined,
        from: toIso(filters.from),
        to: toIso(filters.to),
        q: filters.q || undefined,
        limit: 20,
        cursor,
      });
    },
    [filters]
  );

  const firstLoadRef = useRef("");
  useEffect(() => {
    if (firstLoadRef.current === queryKey) {
      return;
    }
    firstLoadRef.current = queryKey;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const queries =
          statuses.length > 0
            ? statuses
            : [undefined as EventStatus | undefined];
        const results = await Promise.all(
          queries.map((s) => fetchPage(s))
        );
        if (!cancelled) {
          setItems(mergeById(results.map((r) => r.events)));
          setCursors(results.map((r) => r.next_cursor));
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
  }, [queryKey, statuses, fetchPage, t]);

  async function loadMore() {
    const queries =
      statuses.length > 0 ? statuses : [undefined as EventStatus | undefined];
    const pending = queries
      .map((s, i) => ({ status: s, cursor: cursors[i] }))
      .filter((q) => q.cursor !== null && q.cursor !== undefined);
    if (pending.length === 0 || loadingMore) {
      return;
    }
    setLoadingMore(true);
    try {
      const results = await Promise.all(
        pending.map((q) =>
          fetchPage(q.status, q.cursor as number).then((r) => ({
            index: queries.indexOf(q.status),
            result: r,
          }))
        )
      );
      const newCursors = [...cursors];
      for (const { index, result } of results) {
        newCursors[index] = result.next_cursor;
      }
      setCursors(newCursors);
      setItems((prev) =>
        mergeById([prev, ...results.map((r) => r.result.events)])
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t.common.connectionError);
    } finally {
      setLoadingMore(false);
    }
  }

  const hasMore = cursors.some((c) => c !== null && c !== undefined);

  async function handleAction(event: V1Event, action: "acknowledge" | "resolve") {
    setActing(event.id);
    setActionError(null);
    try {
      const updated = await patchEvent(event.id, action);
      setItems((prev) => {
        // Na aba "Ativos", um evento resolvido sai da lista.
        if (tab === "active" && updated.status === "resolved") {
          return prev.filter((e) => e.id !== updated.id);
        }
        return prev.map((e) => (e.id === updated.id ? updated : e));
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setActionError(t.common.unauthorized);
      } else {
        setActionError(
          err instanceof Error ? err.message : t.events.actionFailed
        );
      }
    } finally {
      setActing(null);
    }
  }

  function updateFilters(patch: Partial<Filters>) {
    setFilters((f) => ({ ...f, ...patch }));
  }

  const tabs: { value: Tab; label: string }[] = [
    { value: "active", label: t.status.active },
    { value: "all", label: t.status.allTab },
    { value: "resolved", label: t.status.resolvedTab },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title={t.events.title} subtitle={t.events.subtitle} />

      {/* ABAS */}
      <div
        role="tablist"
        className="panel flex rounded-2xl p-1"
      >
        {tabs.map((tabItem) => (
          <button
            key={tabItem.value}
            role="tab"
            aria-selected={tab === tabItem.value}
            type="button"
            onClick={() => setTab(tabItem.value)}
            className={`min-h-[44px] flex-1 rounded-xl text-sm font-medium transition ${
              tab === tabItem.value
                ? "bg-surface-3 text-ink"
                : "text-faint hover:text-muted"
            }`}
          >
            {tabItem.label}
          </button>
        ))}
      </div>

      {/* FILTROS */}
      <Card>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.events.filterSeverity}
            </span>
            <select
              className="field"
              value={filters.severity}
              onChange={(e) =>
                updateFilters({
                  severity: e.target.value as Filters["severity"],
                })
              }
            >
              <option value="">{t.common.all}</option>
              <option value="info">{t.status.info}</option>
              <option value="warning">{t.status.warning}</option>
              <option value="critical">{t.status.critical}</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.events.filterType}
            </span>
            <select
              className="field"
              value={filters.type}
              onChange={(e) => updateFilters({ type: e.target.value })}
            >
              <option value="">{t.common.all}</option>
              {KNOWN_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.common.from}
            </span>
            <input
              type="datetime-local"
              className="field"
              value={filters.from}
              onChange={(e) => updateFilters({ from: e.target.value })}
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.common.to}
            </span>
            <input
              type="datetime-local"
              className="field"
              value={filters.to}
              onChange={(e) => updateFilters({ to: e.target.value })}
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.common.search}
            </span>
            <div className="relative">
              <Search
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
              />
              <input
                type="search"
                className="field pl-9"
                placeholder={t.events.searchPlaceholder}
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
              />
            </div>
          </label>
        </div>
      </Card>

      {error && <ErrorBanner message={error} />}
      {actionError && <ErrorBanner message={actionError} />}

      {loading ? (
        <LoadingState />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={Bell}
            title={t.events.noEvents}
            message={t.events.noEventsHint}
          />
        </Card>
      ) : (
        <>
          <div className="space-y-3">
            {items.map((event) => (
              <Card key={event.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={event.severity}>
                    {t.status[event.severity]}
                  </Badge>
                  <Badge tone={event.status}>
                    {t.status[event.status]}
                  </Badge>
                  <span className="ml-auto text-xs text-faint">
                    {formatDateTime(
                      event.opened_at ?? event.timestamp,
                      preferences
                    )}
                  </span>
                </div>

                <p className="mt-3 text-sm font-semibold text-ink">
                  {event.event_type}
                </p>
                <p className="mt-1 text-sm text-muted">{event.message}</p>

                <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  <div className="rounded-lg bg-surface-2 px-3 py-2">
                    <p className="text-faint">{t.events.occurrences.replace("{n}", "")}</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {formatNumber(event.occurrences, 0)}
                    </p>
                  </div>
                  <div className="rounded-lg bg-surface-2 px-3 py-2">
                    <p className="text-faint">{t.events.lastValue}</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {event.last_value !== null
                        ? formatNumber(event.last_value, 1)
                        : "--"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-surface-2 px-3 py-2">
                    <p className="text-faint">{t.events.threshold}</p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {event.threshold !== null
                        ? formatNumber(event.threshold, 1)
                        : "--"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-surface-2 px-3 py-2">
                    <p className="text-faint">
                      {event.status === "resolved"
                        ? t.events.closedAt
                        : t.events.lastSeen}
                    </p>
                    <p className="mt-0.5 font-semibold text-ink">
                      {formatDateTime(
                        event.status === "resolved"
                          ? event.closed_at
                          : event.last_seen,
                        preferences
                      ).slice(0, 16)}
                    </p>
                  </div>
                </div>

                {event.recommendation && (
                  <p className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-muted">
                    <span className="font-medium text-ink">
                      {t.events.recommendation}:{" "}
                    </span>
                    {event.recommendation}
                  </p>
                )}

                {(event.status === "open" ||
                  event.status === "acknowledged") && (
                  <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                    {event.status === "open" && (
                      <button
                        type="button"
                        disabled={acting === event.id}
                        onClick={() => handleAction(event, "acknowledge")}
                        className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl bg-surface-3 px-4 text-sm font-medium text-ink disabled:opacity-60"
                      >
                        <Check size={16} />
                        {acting === event.id
                          ? t.events.acknowledging
                          : t.events.acknowledge}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={acting === event.id}
                      onClick={() => handleAction(event, "resolve")}
                      className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl bg-[var(--ok)] px-4 text-sm font-medium text-white disabled:opacity-60"
                    >
                      <Check size={16} />
                      {acting === event.id
                        ? t.events.resolving
                        : t.events.resolve}
                    </button>
                  </div>
                )}
              </Card>
            ))}
          </div>

          {hasMore && (
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="panel min-h-[44px] w-full rounded-2xl text-sm font-medium text-ink disabled:opacity-60"
            >
              {loadingMore ? t.common.loading : t.events.loadMore}
            </button>
          )}
        </>
      )}
    </div>
  );
}

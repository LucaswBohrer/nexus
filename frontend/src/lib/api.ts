import type {
  AnalyticsOverview,
  DiagnosticEpisode,
  DiagnosticResponse,
  ElectricalReading,
  EpisodesResponse,
  EventsV1Params,
  EventsV1Response,
  HealthResponse,
  HistoryBucket,
  HistoryBucketSize,
  HistoryBucketsResponse,
  HistoryExtremesResponse,
  HistoryMetric,
  MonitoringEventsResponse,
  NormalizedSeverity,
  ReportSummary,
  SetSimulationModeResponse,
  SettingsResponse,
  SimulationMode,
  SimulationModeResponse,
  SimulationResetResponse,
  SimulationSessionsResponse,
  SimulationStartRequest,
  SimulationStatus,
  SimulationStopResponse,
  StatsSummary,
  SystemDatabaseResponse,
  SystemErrorsResponse,
  V1Event,
} from "../types/monitoring";

/** Erro HTTP com status e detalhe do backend (ex.: mensagens de 422). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, detail: string | null) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const body = await response.json();
    // FastAPI usa {"detail": ...}; endpoints próprios podem variar.
    const raw = body?.detail ?? body?.message;
    detail =
      typeof raw === "string"
        ? raw
        : raw !== undefined && raw !== null
          ? JSON.stringify(raw)
          : null;
  } catch {
    detail = null;
  }
  return new ApiError(response.status, detail);
}

// Resolve the API base URL at request time, not at build time.
//
// 1. An explicit NEXT_PUBLIC_API_URL always wins.
// 2. Otherwise, assume the API lives on the same host that serves this
//    page, on the backend's default port. This is what makes LAN/mobile
//    access work without rebuilding the frontend: opening
//    http://192.168.x.x:3000 on a phone calls http://192.168.x.x:8000
//    automatically instead of a dead "localhost".
// 3. Server-side (no window) falls back to localhost.
function getApiBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");
  if (fromEnv) {
    return fromEnv;
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }

  return "http://localhost:8000";
}

// Bound every API call: without a timeout a hung backend leaves the
// dashboard's polling promises pending forever (spinner stuck, no error
// banner, requests piling up every 5 s).
const REQUEST_TIMEOUT_MS = 10_000;

function apiFetch(input: RequestInfo | URL, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  // The public demo URL runs behind a localtunnel tunnel, whose
  // "Tunnel website ahead!" interstitial page blocks the dashboard's
  // background fetch() calls even after the page itself was allowed
  // through in the browser. This is the programmatic bypass documented
  // on the interstitial page itself ("set a bypass-tunnel-reminder
  // request header with any value"); top-level page loads are unaffected.
  headers.set("Bypass-Tunnel-Reminder", "1");
  return fetch(input, {
    ...init,
    headers,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
}

function apiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`;
}

/**
 * URL absoluta para EventSource (SSE) — usa a mesma resolução de
 * getApiBaseUrl() que o apiFetch. EventSource não aceita headers
 * customizados (ex.: Bypass-Tunnel-Reminder); se o stream falhar, o
 * chamador deve recorrer ao polling.
 */
export function getStreamUrl(path: string): string {
  return apiUrl(path);
}

export async function getCurrentReading(): Promise<ElectricalReading> {
  const response = await apiFetch(apiUrl("/api/monitoring/current"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch current reading");
  }

  return response.json();
}

export async function getHistory(
  limit: number = 50
): Promise<ElectricalReading[]> {
  const response = await apiFetch(
    apiUrl(`/api/monitoring/history?limit=${limit}`),
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch monitoring history");
  }

  const data = await response.json();
  return data.readings;
}

export async function getEvents(
  limit: number = 10
): Promise<MonitoringEventsResponse> {
  const response = await apiFetch(
    apiUrl(`/api/monitoring/events?limit=${limit}`),
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch monitoring events");
  }

  return response.json();
}

export async function getSimulationMode(): Promise<SimulationMode> {
  const response = await apiFetch(apiUrl("/api/simulation/mode"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch simulation mode");
  }

  const data: SimulationModeResponse = await response.json();
  return data.mode;
}

export async function setSimulationMode(
  mode: SimulationMode
): Promise<SimulationMode> {
  const response = await apiFetch(apiUrl(`/api/simulation/mode/${mode}`), {
    method: "POST",
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: SetSimulationModeResponse = await response.json();
  return data.mode;
}

// ---------------------------------------------------------------------------
// NEXUS 2.3 — Simulation Control Center API
// ---------------------------------------------------------------------------

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await apiFetch(apiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

/** Inicia um cenário de simulação. Erros de validação vêm como 422 com detalhe. */
export async function startSimulation(
  body: SimulationStartRequest
): Promise<SimulationStatus> {
  return postJson<SimulationStatus>("/api/v1/simulation/start", body);
}

/** Status atual — barato e seguro para polling (fonte de verdade do countdown). */
export async function getSimulationStatus(): Promise<SimulationStatus> {
  const response = await apiFetch(apiUrl("/api/v1/simulation/status"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

/** Para a simulação ativa. Idempotente: sem sessão ativa, retorna stopped=false. */
export async function stopSimulation(): Promise<SimulationStopResponse> {
  return postJson<SimulationStopResponse>("/api/v1/simulation/stop", {});
}

/** Volta ao baseline (normal, intensidade 100%, sem timer nem composer). */
export async function resetSimulation(): Promise<SimulationResetResponse> {
  return postJson<SimulationResetResponse>("/api/v1/simulation/reset", {});
}

/** Histórico de sessões, mais recentes primeiro, paginação por cursor de id. */
export async function getSimulationSessions(
  limit = 20,
  cursor?: number | null
): Promise<SimulationSessionsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) {
    params.set("cursor", String(cursor));
  }
  const response = await apiFetch(
    apiUrl(`/api/v1/simulation/sessions?${params.toString()}`),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// NEXUS 2.3 — Reports API
// ---------------------------------------------------------------------------

export type ReportKind = "daily" | "weekly" | "events" | "summary";

function reportQuery(kind: ReportKind, params: Record<string, string>): string {
  const qs = new URLSearchParams(params);
  return `/api/v1/reports/${kind}?${qs.toString()}`;
}

/** Resumo JSON do período — usa as mesmas fórmulas do Analytics (mesma fonte de verdade). */
export async function getReportSummary(
  kind: "daily" | "weekly" | "summary",
  params: Record<string, string>
): Promise<ReportSummary> {
  const response = await apiFetch(
    apiUrl(reportQuery(kind, { ...params, format: "json" })),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

/**
 * Baixa um relatório real como arquivo (CSV ou JSON) via fetch + Blob, para
 * que o header Bypass-Tunnel-Reminder acompanhe a requisição atrás de túneis.
 */
export async function downloadReport(
  kind: ReportKind,
  params: Record<string, string>,
  filename: string
): Promise<void> {
  const response = await apiFetch(apiUrl(reportQuery(kind, params)), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ---------------------------------------------------------------------------
// NEXUS 2.1 — API v1
// ---------------------------------------------------------------------------

/** Diagnóstico atual (regras calculadas no backend, nunca no React). */
export async function getDiagnostics(): Promise<DiagnosticResponse> {
  const response = await apiFetch(apiUrl("/api/monitoring/diagnostics"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiFetch(apiUrl("/api/health"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function getStatsSummary(): Promise<StatsSummary> {
  const response = await apiFetch(apiUrl("/api/v1/stats/summary"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function getHistoryBuckets(params: {
  metric: HistoryMetric;
  from: string;
  to: string;
  bucket: HistoryBucketSize;
}): Promise<HistoryBucket[]> {
  const query = new URLSearchParams({
    metric: params.metric,
    from: params.from,
    to: params.to,
    bucket: params.bucket,
  });
  const response = await apiFetch(apiUrl(`/api/v1/history?${query}`), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: HistoryBucketsResponse = await response.json();
  return data.buckets;
}

export async function getEventsV1(
  params: EventsV1Params = {}
): Promise<EventsV1Response> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.severity)
    query.set("severity", params.severity as NormalizedSeverity);
  if (params.type) query.set("type", params.type);
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  if (params.q) query.set("q", params.q);
  if (params.limit !== undefined)
    query.set("limit", String(params.limit));
  if (params.cursor !== undefined)
    query.set("cursor", String(params.cursor));

  const suffix = query.toString();
  const response = await apiFetch(
    apiUrl(`/api/v1/events${suffix ? `?${suffix}` : ""}`),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function patchEvent(
  id: number,
  action: "acknowledge" | "resolve"
): Promise<V1Event> {
  const response = await apiFetch(apiUrl(`/api/v1/events/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: { event: V1Event } = await response.json();
  return data.event;
}

export async function getSettings(): Promise<Record<string, unknown>> {
  const response = await apiFetch(apiUrl("/api/v1/settings"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: SettingsResponse = await response.json();
  return data.settings;
}

export async function updateSetting(
  key: string,
  value: unknown
): Promise<unknown> {
  const response = await apiFetch(
    apiUrl(`/api/v1/settings/${encodeURIComponent(key)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: { key: string; value: unknown } = await response.json();
  return data.value;
}

export async function getEpisodes(
  limit = 20
): Promise<DiagnosticEpisode[]> {
  const response = await apiFetch(
    apiUrl(`/api/v1/diagnostics/episodes?limit=${limit}`),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  const data: EpisodesResponse = await response.json();
  return data.episodes;
}

export async function getSystemErrors(): Promise<SystemErrorsResponse> {
  const response = await apiFetch(apiUrl("/api/v1/system/errors"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function getSystemDatabase(): Promise<SystemDatabaseResponse> {
  const response = await apiFetch(apiUrl("/api/v1/system/database"), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// NEXUS 2.2 — extremos, análises e stream
// ---------------------------------------------------------------------------

export async function getHistoryExtremes(params: {
  metric: HistoryMetric;
  from: string;
  to: string;
}): Promise<HistoryExtremesResponse> {
  const query = new URLSearchParams({
    metric: params.metric,
    from: params.from,
    to: params.to,
  });
  const response = await apiFetch(apiUrl(`/api/v1/history/extremes?${query}`), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

export async function getAnalyticsOverview(params: {
  from: string;
  to: string;
}): Promise<AnalyticsOverview> {
  const query = new URLSearchParams({
    from: params.from,
    to: params.to,
  });
  const response = await apiFetch(
    apiUrl(`/api/v1/analytics/overview?${query}`),
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json();
}

import type {
  ElectricalReading,
  MonitoringEventsResponse,
  SetSimulationModeResponse,
  SimulationMode,
  SimulationModeResponse,
} from "../types/monitoring";

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
    throw new Error("Failed to set simulation mode");
  }

  const data: SetSimulationModeResponse = await response.json();
  return data.mode;
}

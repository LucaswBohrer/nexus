import type {
  DiagnosticResponse,
  ElectricalReading,
  MonitoringEventsResponse,
} from "../types/monitoring";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getCurrentReading(): Promise<ElectricalReading> {
  const response = await fetch(`${API_URL}/api/monitoring/current`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch current reading");
  }

  return response.json();
}

export async function getDiagnostics(): Promise<DiagnosticResponse> {
  const response = await fetch(`${API_URL}/api/monitoring/diagnostics`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch diagnostics");
  }

  return response.json();
}

export async function getHistory(
  limit: number = 50
): Promise<ElectricalReading[]> {
  const response = await fetch(
    `${API_URL}/api/monitoring/history?limit=${limit}`,
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
  const response = await fetch(
    `${API_URL}/api/monitoring/events?limit=${limit}`,
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch monitoring events");
  }

  return response.json();
}
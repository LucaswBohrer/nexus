import type {
  DiagnosticResponse,
  ElectricalReading,
  MonitoringEventsResponse,
} from "../types/monitoring";

const API_URL = "http://localhost:8000";

export async function getCurrentReading(): Promise<ElectricalReading> {
  const response = await fetch(
    `${API_URL}/api/monitoring/current`,
<<<<<<< HEAD
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error(
      "Failed to fetch current reading"
    );
=======
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch current reading");
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
  }

  return response.json();
}

export async function getDiagnostics(): Promise<DiagnosticResponse> {
  const response = await fetch(
    `${API_URL}/api/monitoring/diagnostics`,
<<<<<<< HEAD
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error(
      "Failed to fetch diagnostics"
    );
=======
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch diagnostics");
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
  }

  return response.json();
}

export async function getHistory(
  limit: number = 50
): Promise<ElectricalReading[]> {
  const response = await fetch(
    `${API_URL}/api/monitoring/history?limit=${limit}`,
<<<<<<< HEAD
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error(
      "Failed to fetch monitoring history"
    );
  }

  const data = await response.json();

=======
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch monitoring history");
  }

  const data = await response.json();
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
  return data.readings;
}

export async function getEvents(
  limit: number = 10
): Promise<MonitoringEventsResponse> {
  const response = await fetch(
    `${API_URL}/api/monitoring/events?limit=${limit}`,
<<<<<<< HEAD
    {
      cache: "no-store",
    }
  );

  if (!response.ok) {
    throw new Error(
      "Failed to fetch monitoring events"
    );
=======
    { cache: "no-store" }
  );

  if (!response.ok) {
    throw new Error("Failed to fetch monitoring events");
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
  }

  return response.json();
}
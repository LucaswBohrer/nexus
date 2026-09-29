export interface ElectricalReading {
  timestamp: string;
  voltage: number;
  current: number;
  frequency: number;
  power_factor: number;
  active_power: number;
  temperature: number;
  status: "normal" | "warning" | "critical";
}

export interface MonitoringEvent {
  id: number;
  timestamp: string;
  event_type: string;
  severity: "low" | "medium" | "high";
  message: string;
  recommendation: string;
}

export interface Diagnosis {
  status: "normal" | "warning" | "critical";
  severity: "low" | "medium" | "high";
  anomalies: string[];
  recommendations: string[];
  events: MonitoringEvent[];
}

export interface DiagnosticResponse {
  reading: ElectricalReading;
  diagnosis: Diagnosis;
}

export interface MonitoringEventsResponse {
  events: MonitoringEvent[];
}
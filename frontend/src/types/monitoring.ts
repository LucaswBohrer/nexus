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

<<<<<<< HEAD
=======
export interface MonitoringEvent {
  id: number;
  timestamp: string;
  event_type: string;
  severity: "low" | "medium" | "high";
  message: string;
  recommendation: string;
}

>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
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

<<<<<<< HEAD
export interface MonitoringEvent {
  id: number;
  timestamp: string;
  event_type: string;
  severity: "low" | "medium" | "high";
  message: string;
  recommendation: string;
}

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
export interface MonitoringEventsResponse {
  events: MonitoringEvent[];
}
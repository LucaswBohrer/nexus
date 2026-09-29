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

/** Legado: GET /api/monitoring/events mapeia de volta para low/medium/high. */
export interface MonitoringEvent {
  id: number;
  timestamp: string;
  event_type: string;
  severity: "low" | "medium" | "high";
  message: string;
  recommendation: string;
}

/** Severidade normalizada (NEXUS 2.1): usada em eventos v1 e diagnósticos. */
export type NormalizedSeverity = "info" | "warning" | "critical";

export type EventStatus = "open" | "acknowledged" | "resolved";

export interface V1Event {
  id: number;
  timestamp: string;
  event_type: string;
  severity: NormalizedSeverity;
  message: string;
  recommendation: string;
  status: EventStatus;
  opened_at: string | null;
  closed_at: string | null;
  last_seen: string | null;
  occurrences: number;
  last_value: number | null;
  threshold: number | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  equipment_id: string | null;
}

export interface EventsV1Response {
  events: V1Event[];
  next_cursor: number | null;
}

export interface EventsV1Params {
  status?: EventStatus;
  severity?: NormalizedSeverity;
  type?: string;
  from?: string;
  to?: string;
  q?: string;
  limit?: number;
  cursor?: number;
}

export interface Diagnosis {
  status: "normal" | "warning" | "critical";
  severity: NormalizedSeverity;
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

export type SimulationMode =
  | "normal"
  | "high_voltage"
  | "low_voltage"
  | "low_power_factor"
  | "high_temperature"
  | "multiple_anomalies";

export interface SimulationModeResponse {
  mode: SimulationMode;
}

export interface SetSimulationModeResponse {
  mode: SimulationMode;
  status: string;
}

export interface HistoryBucket {
  t: string;
  min: number;
  max: number;
  avg: number;
  count: number;
}

export interface HistoryBucketsResponse {
  buckets: HistoryBucket[];
}

export type HistoryMetric =
  | "voltage"
  | "current"
  | "active_power"
  | "power_factor"
  | "temperature"
  | "frequency"
  | "apparent_power";

export type HistoryBucketSize = "1m" | "5m" | "15m" | "1h" | "1d";

export interface MetricAggregate {
  min: number;
  max: number;
  avg: number;
}

export interface StatsSummary {
  energy_today_kwh: number;
  readings_count: number;
  uptime_s: number;
  current: ElectricalReading;
  last_24h: Record<string, MetricAggregate>;
  status_counts_24h: Record<string, number>;
}

export interface DiagnosticEpisode {
  id: number;
  started_at: string;
  ended_at: string | null;
  status: "open" | "resolved";
  severity: NormalizedSeverity;
  rules: string[];
  peak_values: Record<string, { min: number; max: number }>;
  recommendations: string[];
}

export interface EpisodesResponse {
  episodes: DiagnosticEpisode[];
}

export interface HealthResponse {
  status: string;
  service: string;
  database: string;
  version?: string;
  uptime_s?: number;
  db_size_bytes?: number;
  readings_count?: number;
  last_tick_age_ms?: number;
}

export interface SystemError {
  timestamp: string;
  message: string;
  context?: string;
}

export interface SystemErrorsResponse {
  errors: SystemError[];
}

export interface SystemDatabaseResponse {
  path: string;
  size_bytes: number;
  tables: string[];
  user_version: number;
  journal_mode: string;
}

export type SettingValue = string | number | boolean | null | undefined;

export interface SettingsResponse {
  settings: Record<string, SettingValue>;
}

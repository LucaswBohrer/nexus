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
  /** NEXUS 2.4: id ou código do equipamento; omitido = DEFAULT. */
  equipment_id?: number | string | null;
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
  | "multiple_anomalies"
  | "sensor_failure"
  | "oscillation"
  | "overload";

/** Anomalias combináveis no composer (sensor_failure não combina — rejeitado pelo backend). */
export type AnomalyKey =
  | "high_voltage"
  | "low_voltage"
  | "low_power_factor"
  | "high_temperature"
  | "overload"
  | "oscillation";

export interface SimulationModeResponse {
  mode: SimulationMode;
}

export interface SetSimulationModeResponse {
  mode: SimulationMode;
  status: string;
}

/** Status barato para polling — fonte de verdade é o backend. */
export interface SimulationStatus {
  running: boolean;
  session_id: number | null;
  mode: SimulationMode;
  intensity: number;
  anomalies: string[];
  started_at: string | null;
  ends_at: string | null;
  remaining_seconds: number | null;
}

export interface SimulationStartRequest {
  mode: SimulationMode;
  intensity?: number;
  duration_minutes?: number | null;
  anomalies?: string[];
  /** NEXUS 2.4: id ou código do equipamento; omitido = DEFAULT. */
  equipment_id?: number | string | null;
}

export interface SimulationStopResponse extends SimulationStatus {
  stopped: boolean;
}

export interface SimulationResetResponse extends SimulationStatus {
  reset: boolean;
  finished_session?: SimulationSession | null;
}

export interface SimulationSessionParameters {
  mode: SimulationMode;
  intensity: number;
  duration_minutes: number | null;
  anomalies: string[];
}

export interface SimulationSession {
  id: number;
  mode: SimulationMode;
  parameters: SimulationSessionParameters | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  peak_values: Record<string, { min: number; max: number }> | null;
  status: "running" | "finished" | "interrupted";
}

export interface SimulationSessionsResponse {
  sessions: SimulationSession[];
  next_cursor: number | null;
}

export interface ReportPeriod {
  from: string;
  to: string;
}

export interface ReportSummary {
  period: ReportPeriod;
  summary: {
    readings_count: number;
    energy_kwh: number;
    power_avg: number | null;
    power_max: number | null;
    voltage_avg: number | null;
    voltage_min: number | null;
    voltage_max: number | null;
    power_factor_avg: number | null;
    temperature_max: number | null;
  };
  status: { normal: number; warning: number; critical: number };
  events: V1Event[];
  events_truncated: boolean;
  diagnostic_episodes: DiagnosticEpisode[];
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

// ---------------------------------------------------------------------------
// NEXUS 2.2 — stream (SSE), extremos e análises
// ---------------------------------------------------------------------------

/** Evento SSE de GET /api/v1/stream/readings. */
export interface StreamReadingEvent {
  reading: ElectricalReading;
  diagnosis_status: "normal" | "warning" | "critical";
  severity: NormalizedSeverity;
  server_ts: string;
}

export interface ExtremePoint {
  value: number;
  timestamp: string;
}

/** GET /api/v1/history/extremes — null quando o período está vazio. */
export interface HistoryExtremesResponse {
  metric: HistoryMetric;
  from: string;
  to: string;
  min: ExtremePoint | null;
  max: ExtremePoint | null;
  avg: number | null;
  count: number;
}

/** GET /api/v1/analytics/overview — agregados reais do período. */
export interface AnalyticsOverview {
  from: string;
  to: string;
  readings_count: number;
  energy_kwh: number;
  per_metric: Record<string, MetricAggregate>;
  events_by_severity: Record<string, number>;
  events_by_status: Record<string, number>;
  episodes: {
    total: number;
    open: number;
  };
}

// ---------------------------------------------------------------------------
// NEXUS 2.4 — equipment registry
// ---------------------------------------------------------------------------

/** Status operacional de um equipamento. */
export type EquipmentStatus = "active" | "inactive" | "maintenance";

/** Registro de um equipamento/fonte de telemetria. */
export interface Equipment {
  id: number;
  code: string;
  name: string;
  description: string | null;
  equipment_type: string | null;
  location: string | null;
  status: EquipmentStatus;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** Payload de criação (POST /api/v1/equipment). */
export interface EquipmentCreatePayload {
  name: string;
  code?: string | null;
  description?: string | null;
  equipment_type?: string | null;
  location?: string | null;
  status?: EquipmentStatus;
  enabled?: boolean;
}

/** Payload de atualização parcial (PATCH /api/v1/equipment/{id}). */
export interface EquipmentUpdatePayload {
  name?: string;
  code?: string;
  description?: string | null;
  equipment_type?: string | null;
  location?: string | null;
  status?: EquipmentStatus;
  enabled?: boolean;
}

/** Diagnóstico recomputado pelo backend a partir da última leitura real. */
export interface EquipmentDiagnosis {
  status: "normal" | "warning" | "critical";
  severity: NormalizedSeverity;
  anomalies: string[];
  recommendations: string[];
}

/** GET /api/v1/equipment/{id}/summary — tudo de dados reais armazenados. */
export interface EquipmentSummary {
  equipment: Equipment;
  last_reading: ElectricalReading | null;
  last_reading_at: string | null;
  diagnosis: EquipmentDiagnosis | null;
  active_events: number;
  open_episodes: number;
  readings_count: number;
}

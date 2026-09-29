# NEXUS API v1 (backend 2.3)

New functionality lives under `/api/v1/*`. The legacy `/api/*` endpoints
keep their exact paths, formats and status codes — see
[Legacy compatibility](#legacy-compatibility) below.

Interactive docs: `http://localhost:8000/docs`

## Conventions

- Timestamps are ISO-8601 **UTC** (`2026-09-29T22:10:28.123456+00:00`).
  Naive `from`/`to` query values are interpreted as **UTC** (all stored
  timestamps are UTC).
- Severities are normalized to `info` / `warning` / `critical`.
- Validation failures return `422` with a `detail` message; unknown ids
  return `404`.

## Settings

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/settings` | All settings with effective values |
| `GET` | `/api/v1/settings/{key}` | Single setting (`404` on unknown key) |
| `PUT` | `/api/v1/settings/{key}` | Update (`{"value": ...}`; `422` on invalid) |

Settings are persisted in the `settings` table (JSON-encoded) and cached
in memory; writes invalidate the cache. Threshold changes take effect on
the next tick — no restart needed.

Defaults: `thresholds.voltage_min/max` 198/242 V, `thresholds.frequency_min/max`
59.5/60.5 Hz, `thresholds.power_factor_min` 0.8, `thresholds.temperature_max`
70 °C, retention 30/90/90/180 days (readings/events/episodes/simulation
sessions), `simulation.default_intensity` 100.

## History / aggregation

Computed in SQL from the real stored readings — the frontend never
receives thousands of raw rows.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/history?metric=&from=&to=&bucket=` | Time-bucketed aggregates |
| `GET` | `/api/v1/history/extremes?metric=&from=&to=` | Min/max/avg with extreme timestamps |
| `GET` | `/api/v1/stats/summary` | Consolidated dashboard statistics |
| `GET` | `/api/v1/analytics/overview?from=&to=` | Period analytics: readings, energy, events, episodes |

`GET /api/v1/history` parameters:

- `metric`: `voltage`, `current`, `active_power`, `power_factor`,
  `temperature`, `frequency`, `apparent_power` (derived: `voltage*current/1000`, kVA).
- `from`, `to`: ISO-8601 bounds (naive = UTC).
- `bucket`: `1m`, `5m`, `15m`, `1h`, `1d` (default `5m`).

Limits (violations → `422`): range ≤ 31 days, buckets ≤ 2000.

Response:

```json
{ "buckets": [ { "t": "2026-09-29T22:10:00+00:00",
                 "min": 218.1, "max": 221.9, "avg": 220.0, "count": 60 } ] }
```

`GET /api/v1/stats/summary` returns:

```json
{ "energy_today_kwh": 1.234,
  "readings_count": 86400,
  "uptime_s": 3600.5,
  "current": { ...latest reading... },
  "last_24h": { "voltage": {"min":..,"max":..,"avg":..}, ... },
  "status_counts_24h": { "normal": 86000, "warning": 400 } }
```

Energy is integrated from **real timestamp deltas**
(`power_kw × delta_s / 3600`), so tick drift cannot skew it. Deltas longer
than 300 s (restart/outage gaps) are excluded rather than inflated.

`GET /api/v1/history/extremes` takes `metric`, `from`, `to` (same metrics
and ≤31-day limit as `/history`; violations → `422`) and returns:

```json
{ "metric": "voltage", "from": "...", "to": "...",
  "min": { "value": 215.0, "timestamp": "2026-09-29T20:02:00+00:00" },
  "max": { "value": 230.0, "timestamp": "2026-09-29T20:03:00+00:00" },
  "avg": 222.4, "count": 5 }
```

`min`/`max` carry the timestamp of the extreme reading (earliest wins on
ties). Empty ranges return `null` extremes with `count: 0`.

`GET /api/v1/analytics/overview` takes `from`, `to` (naive = UTC, ≤31
days, `422` on violations) and aggregates the whole period from the real
tables — nothing is invented:

```json
{ "from": "...", "to": "...",
  "readings_count": 86400,
  "energy_kwh": 12.34,
  "per_metric": { "voltage": {"min":..,"max":..,"avg":..}, ... },
  "events_by_severity": { "info": 0, "warning": 3, "critical": 1 },
  "events_by_status": { "open": 1, "acknowledged": 1, "resolved": 2 },
  "episodes": { "total": 2, "open": 1 } }
```

`energy_kwh` uses the same real-delta integration (300 s cap) as the
summary endpoint. Event/episode counts are filtered by `opened_at` /
`started_at` inside the range.

## Real-time stream (SSE)

`GET /api/v1/stream/readings` is a Server-Sent Events stream at ~1 Hz:

- Response headers: `Content-Type: text/event-stream`,
  `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- Each `data:` event is JSON:
  `{ "reading": {...}, "diagnosis_status": "normal|warning|critical",
    "severity": "info|warning|critical",
    "server_ts": "2026-09-29T22:50:01+00:00" }`.
- A `: heartbeat` comment is sent every 15 s so buffering proxies and
  tunnels do not stall the connection.
- The generator samples the shared telemetry state — no per-client
  buffers, so concurrent clients cannot leak memory. Client disconnects
  are handled silently (no traceback spam).
- Public like every other `GET` (`NEXUS_API_KEY` only guards writes).
  Clients should fall back to polling `/api/monitoring/current` if the
  stream cannot be established.

## Events

Conditions are deduplicated by `(event_type, equipment_id)`: a sustained
anomaly produces **one** event row with an incrementing `occurrences`
counter, not one row per tick.

### Lifecycle

`open` → `acknowledged` → `resolved`. A condition absent for 5 consecutive
ticks resolves its event automatically (`closed_at` set). A **resolved
event is never reopened** — a later occurrence creates a new event.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/events` | Filtered list, latest first |
| `PATCH` | `/api/v1/events/{id}` | `{"action": "acknowledge"}` or `{"action": "resolve"}` |

`GET /api/v1/events` filters: `status` (`open`/`acknowledged`/`resolved`),
`severity` (`info`/`warning`/`critical`), `type`, `from`, `to`, `q`
(substring search in message), `limit` (1–200, default 50), `cursor`
(event id for pagination). Response: `{"events": [...], "next_cursor": 42|null}`.

`PATCH` transitions: `open → acknowledged`, `open → resolved`,
`acknowledged → resolved`. Anything else (including any transition out of
`resolved`, or an unknown action) returns `422`; unknown ids return `404`.

## Diagnostics

A **diagnostic episode** is the whole-system view of an abnormal period
(per-condition detail lives in events). Rules mirror the event lifecycle:
the system entering an abnormal state with no open episode opens one;
while abnormal the open episode is updated (severity = worst seen,
`rules`/`recommendations` unioned, `peak_values` track per-metric
min/max actually observed); 5 consecutive normal ticks close it
(`status='resolved'`, `ended_at` set).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/diagnostics/episodes` | Episodes, latest first |

`GET /api/v1/diagnostics/episodes` params: `limit` (1–200, default 20).
Response: `{"episodes": [{"id", "started_at", "ended_at", "status",
"severity", "rules": [...], "peak_values": {"voltage": {"min", "max"}, ...},
"recommendations": [...]}]}`.

## Simulation (2.3)

The simulation control center. Scenarios describe *deviations from the
nominal operating point* (220 V, 12 A, 60 Hz, PF 0.93, 42 °C); **intensity**
0–200 % scales each deviation deterministically (`nominal + (target −
nominal) × intensity/100`), so 100 % reproduces the historical behaviour,
0 % collapses to nominal and 200 % doubles the deviation. Physical clamps
and the `active_power = V·I·PF/1000` chain hold at every intensity.

Modes: `normal`, `high_voltage`, `low_voltage`, `low_power_factor`,
`high_temperature`, `multiple_anomalies`, plus the 2.3 additions:
`sensor_failure` (values freeze; the reading is flagged `stale` and the
diagnostics engine raises a `SENSOR_STALE` warning — no fake-normal
values), `oscillation` (deterministic 24-tick sine wave on voltage,
±15 V at 100 %), `overload` (current ≈ 28 A, active power rises
consistently). The optional `anomalies` composer list adds extra anomaly
keys on top of the mode (e.g. `high_voltage` + `high_temperature`);
entries are validated, `sensor_failure` cannot be combined.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/simulation/start` | Start a scenario (API key) |
| `GET` | `/api/v1/simulation/status` | Live status, cheap for polling |
| `POST` | `/api/v1/simulation/stop` | Stop, idempotent (API key) |
| `POST` | `/api/v1/simulation/reset` | Reset to baseline (API key) |
| `GET` | `/api/v1/simulation/sessions` | Session history, id-cursor paging |

`POST /api/v1/simulation/start` body: `{"mode", "intensity" (0–200,
default 100), "duration_minutes" (null = indefinite, otherwise a positive
number of minutes — fractional values allowed), "anomalies": [...]}`.
Invalid payloads return `422`. Starting `normal` with no anomalies stops
any active session without creating an audit row; any other start
supersedes a running session (it is finished first — states never
overlap).

`GET /api/v1/simulation/status` returns `running`, `session_id`, `mode`,
`intensity`, `anomalies`, `started_at`, `ends_at` and `remaining_seconds`
(computed server-side; 0 when idle, null when indefinite).

**Auto-revert:** the backend owns the timer. Every telemetry tick checks
whether `ends_at` passed; when it does, the session is finished
(`ended_at` + `peak_values` persisted) and the simulator returns to
normal — with no frontend connected. One internal `_finish_session()`
serves stop/reset/auto-revert/supersede, so the logic cannot diverge.

`GET /api/v1/simulation/sessions` params: `limit` (1–200, default 50),
`cursor` (session id). Each item: `id`, `mode`, `parameters`,
`started_at`, `ended_at`, `duration_s`, `peak_values` (per-metric
min/max tracked in memory during the session), `status`
(`running`/`finished`/`interrupted`, derived — a row with no `ended_at`
that is not active means the process died mid-session).

## Reports (2.3)

JSON summaries and streaming CSV exports. The JSON summary is built
directly on `get_analytics_overview()` — reports and analytics share
the exact same formulas, so they can never disagree. CSVs stream
row-by-row (`fetchmany` batches) and are never fully built in memory
(no `Content-Length`; chunked transfer). All ranges are capped at 31
days (`422` beyond).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/reports/daily` | One UTC day (`?date=YYYY-MM-DD`, default today) |
| `GET` | `/api/v1/reports/weekly` | One ISO week (`?week=YYYY-Www`, default current) |
| `GET` | `/api/v1/reports/events` | Events in `?from=&to=` |
| `GET` | `/api/v1/reports/summary` | Custom period `?from=&to=` |

All four accept `?format=json` (default) or `?format=csv`. For
`daily`/`weekly`/`summary`, CSV streams the readings
(`timestamp,voltage,current,frequency,power_factor,active_power,temperature,status`);
for `events`, CSV streams the events
(`timestamp,event_type,severity,status,message,recommendation,occurrences,opened_at,closed_at,last_value,threshold`).

The JSON report shape: `{"period": {"from","to"}, "summary":
{"readings_count","energy_kwh","power_avg","power_max","voltage_avg","voltage_min","voltage_max","power_factor_avg","temperature_max"},
"status": {"normal","warning","critical"}, "events": [...],
"events_truncated": bool, "diagnostic_episodes": [...]}`.

## Health / system

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness + SQLite check (503 if DB unreachable) |
| `GET` | `/api/v1/system/errors` | Last 100 process errors, latest first |
| `GET` | `/api/v1/system/database` | DB introspection |

`GET /api/health` keeps the legacy `status`/`service`/`database` keys and
adds `version`, `uptime_s`, `db_size_bytes`, `readings_count` and
`last_tick_age_ms`.

`GET /api/v1/system/database` returns `path`, `size_bytes`, `tables`,
`user_version` (schema migration version) and `journal_mode`.

`GET /api/v1/system/errors` reads an in-memory ring buffer: telemetry tick
failures and unhandled exceptions are recorded with timestamp, message
and context. It is process observability, not an audit log.

## Write protection (optional API key)

Set `NEXUS_API_KEY` to require an `X-API-Key` header on **all**
`POST`/`PUT`/`PATCH` endpoints — including the legacy
`POST /api/simulation/mode/{mode}`. Missing or wrong key → `401`.
Unset → writes stay open. `GET`s are always public.

This is demo-grade protection, not real authentication: never ship the
key to the frontend.

## Logging

`NEXUS_LOG_JSON=1` switches application logging to one JSON object per
line (`{"ts","level","logger","message"}`), using the stdlib only.

## Migrations

Schema changes are versioned with `PRAGMA user_version` in
`backend/app/database/migrations.py` (idempotent, applied on startup):

- **v1**: `idx_readings_ts` index; lifecycle columns on `monitoring_events`;
  `diagnostic_episodes`, `simulation_sessions`, `settings` tables;
  legacy naive timestamps interpreted as `America/Sao_Paulo` and converted
  to UTC (legacy events become `resolved` with `occurrences=1`).
- **v2**: `normal_streak` counter column on `monitoring_events`.
- **v3**: `normal_streak` counter column on `diagnostic_episodes`
  (episodes close after K consecutive normal ticks).

## Data retention

Enforced on startup and hourly by the telemetry loop (windows are
settings, defaults below):

| Data | Default |
|---|---|
| Readings | 30 days |
| Events | 90 days |
| Diagnostic episodes | 90 days |
| Simulation sessions | 180 days |
| Settings | permanent |

## Legacy compatibility

These endpoints are byte-for-byte compatible with the pre-2.1 contract
(paths, formats, status codes):

- `GET /`, `GET /api/health`, `GET /api/monitoring/current`,
  `GET /api/monitoring/diagnostics`, `GET /api/monitoring/history`,
  `GET /api/monitoring/events`, `GET /api/simulation/mode`,
  `POST /api/simulation/mode/{mode}`

Notes:

- `GET /api/monitoring/events` returns the legacy 6-column format; the
  stored `info`/`warning`/`critical` severities are mapped back to
  `low`/`medium`/`high`.
- `GET /api/health` only gained additive fields.
- `POST /api/simulation/mode/{mode}` accepts the API-key dependency when
  `NEXUS_API_KEY` is set; behavior is unchanged otherwise. Since 2.3 it is
  a thin wrapper over `POST /api/v1/simulation/start` (intensity 100 %,
  no duration, no composer anomalies) and records a session row.

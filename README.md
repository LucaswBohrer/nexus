# NEXUS — Intelligent Electrical Monitoring System

NEXUS is a full-stack platform for **simulating, monitoring and diagnosing electrical systems in real time** — no physical hardware required. It streams virtual telemetry through a FastAPI backend, detects anomalous conditions with a diagnostic engine, persists everything in SQLite, and presents it on a live Next.js dashboard that works on desktop and on your phone.

> **Status:** ✅ Demo-ready — run `./start.sh` and open the dashboard.

---

## The problem it solves

Supervising electrical installations (voltage, current, power factor, temperature) normally requires physical meters, wiring and SCADA-style software. NEXUS provides a complete monitoring loop — acquisition, diagnostics, persistence, visualization — driven by a **configurable electrical simulator**, so monitoring logic, alerting and dashboards can be developed and demonstrated without any hardware.

---

## Features

- Live electrical telemetry sampled at 1 Hz (voltage, current, frequency, power factor, active power, temperature)
- Automatic anomaly detection with severity classification (`normal` / `warning` / `critical`)
- Diagnostic messages + maintenance recommendations per anomaly
- Persistent monitoring events
- SQLite persistence with 30-day retention and automatic pruning
- Power history chart with live updates
- 9 configurable simulation scenarios, switchable from the dashboard
- REST API with validated pagination limits
- Real SQLite health check (`/api/health` → 503 when the database is unreachable)
- Automatic recovery from a corrupt SQLite file (quarantines it, starts fresh)
- LAN-ready: dashboard reachable from phones/tablets on the same Wi-Fi
- Responsive dashboard (desktop, notebook, tablet, phone)

---

## Architecture

```text
Frontend
   ↓
REST API
   ↓
Monitoring/Diagnostics
   ↓
SQLite
   ↑
Telemetry Simulator
```

- **Telemetry Simulator** (`backend/app/engine/simulator.py`) generates realistic 220 V / 60 Hz readings at 1 Hz. Six scenarios alter the signal to reproduce fault conditions.
- **Monitoring/Diagnostics** (`backend/app/engine/diagnostics.py`, `backend/app/services/monitoring.py`) evaluates every reading against operating ranges, classifies severity, and emits monitoring events with recommendations.
- **SQLite** (`backend/app/database/database.py`) persists readings and events, prunes data older than 30 days, and recovers automatically from corruption at startup.
- **REST API** (`backend/app/api/routes.py`, FastAPI) exposes current readings, history, events, diagnostics and simulation control.
- **Frontend** (`frontend/`, Next.js + React + Tailwind) polls the API every 5 s and renders metrics, chart, diagnostics and events. The API base URL resolves at runtime from the page host, so the same build works on `localhost` and on a phone over LAN.

---

## Simulation modes

Switch scenarios from the dashboard header (flask icon) or via `POST /api/simulation/mode/{mode}`:

| Mode | What it demonstrates |
|---|---|
| `normal` | Healthy 220 V / 60 Hz operation, PF ≈ 0.93 |
| `high_voltage` | Sustained ~250 V — triggers `HIGH_VOLTAGE` warnings |
| `low_voltage` | Sustained ~190 V — triggers `LOW_VOLTAGE` warnings |
| `low_power_factor` | PF ≈ 0.68 — triggers `LOW_POWER_FACTOR` (reactive power issues) |
| `high_temperature` | Equipment ≈ 78 °C — triggers high-severity `HIGH_TEMPERATURE` events |
| `multiple_anomalies` | High voltage + low PF + high temperature — `critical` system status |
| `sensor_failure` | Frozen readings flagged `stale` — raises `SENSOR_STALE` warnings |
| `oscillation` | Deterministic 24-tick sine wave on voltage (±15 V at 100 %) |
| `overload` | Current ≈ 28 A — active power rises consistently |

The 2.3 simulation control API (`/api/v1/simulation/*`) adds intensity
(0–200 %), durations with backend-owned auto-revert, a multi-anomaly
composer, session history with peak values, and the legacy endpoints
above keep working as thin wrappers over it. Reports
(`/api/v1/reports/*`) export JSON summaries and streaming CSVs.

The dashboard reacts within seconds: metric cards change state, the diagnostics panel flags parameters, and events appear in the activity feed.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts, Lucide |
| Backend | Python, FastAPI, Pydantic v2 |
| Database | SQLite (WAL-friendly, single file) |
| API | REST + JSON, OpenAPI docs at `/docs` |
| Tests | stdlib `unittest` + live uvicorn subprocesses (no extra test deps) |

---

## Quickstart

Requirements: **Python 3.10+** and **Node.js 18+**.

```sh
./start.sh
```

This creates the backend venv, installs dependencies, detects your LAN IP, configures CORS for local + LAN access, and starts both services:

| | URL |
|---|---|
| Dashboard (this computer) | http://localhost:3000 |
| Dashboard (phone, same Wi-Fi) | http://`YOUR-PC-IP`:3000 |
| API docs | http://`YOUR-PC-IP`:8000/docs |

Press `Ctrl+C` to stop both.

> On Windows, `start.sh` doesn't run natively — follow the manual steps below, using `uvicorn ... --host 0.0.0.0` for LAN access.

---

## Manual setup

### Backend

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Local only:
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# LAN-accessible (phone demo):
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```sh
cd frontend
npm install
npm run dev
# LAN-accessible:
npx next dev --hostname 0.0.0.0 --port 3000
```

---

## Access from your phone (same Wi-Fi)

1. Start everything with `./start.sh` (or manually with the LAN flags above).
2. Find your computer's LAN IP:
   - Linux: `hostname -I`
   - macOS: `ipconfig getifaddr en0`
   - Windows: `ipconfig` (look for "IPv4 Address")
3. On your phone's browser open `http://YOUR-PC-IP:3000` (e.g. `http://192.168.1.42:3000`).

No rebuild or phone-side configuration needed: the dashboard calls the API on the same host that serves the page (`http://YOUR-PC-IP:8000`). To point the dashboard at a different API explicitly, set `NEXT_PUBLIC_API_URL` (see Configuration).

CORS is an explicit allowlist controlled by `NEXUS_CORS_ORIGINS` (never `*`). `./start.sh` sets it to `http://localhost:3000,http://YOUR-PC-IP:3000` automatically; when starting manually, export it yourself:

```sh
export NEXUS_CORS_ORIGINS="http://localhost:3000,http://192.168.1.42:3000"
```

---

## Configuration

Backend (`backend/.env`, all prefixed with `NEXUS_`):

| Variable | Default | Description |
|---|---|---|
| `NEXUS_HOST` | `127.0.0.1` | API bind address used by `start.sh` (`0.0.0.0` for LAN) |
| `NEXUS_PORT` | `8000` | API port |
| `NEXUS_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `NEXUS_DATABASE_URL` | `nexus.db` | SQLite path (relative to `backend/` or absolute) |

Frontend (`frontend/.env.local`, optional):

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | _(same host, port 8000)_ | Override the API base URL |

See `backend/.env.example` and `frontend/.env.example`.

---

## API

Interactive docs: `http://localhost:8000/docs`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness + real SQLite check (503 if DB unreachable) |
| `GET` | `/api/monitoring/current` | Latest telemetry reading |
| `GET` | `/api/monitoring/history?limit=N` | Persisted readings (`1–1000`, default 100) |
| `GET` | `/api/monitoring/events?limit=N` | Monitoring events (`1–500`, default 100) |
| `GET` | `/api/monitoring/diagnostics` | Current reading + diagnostic analysis |
| `GET` | `/api/simulation/mode` | Active simulation scenario |
| `POST` | `/api/simulation/mode/{mode}` | Switch scenario (400 on unknown mode) |

**API v1** (2.1/2.2 — full reference in [`docs/api-v1.md`](docs/api-v1.md)):

| Method | Endpoint | Description |
|---|---|---|
| `GET` / `PUT` | `/api/v1/settings[/{key}]` | Persistent system settings (thresholds, retention) |
| `GET` | `/api/v1/history?metric=&from=&to=&bucket=` | Time-bucketed aggregates (≤31 d, ≤2000 buckets) |
| `GET` | `/api/v1/history/extremes?metric=&from=&to=` | Min/max/avg with extreme timestamps (2.2) |
| `GET` | `/api/v1/stats/summary` | Energy (real deltas), 24h min/max/avg, status counts |
| `GET` | `/api/v1/analytics/overview?from=&to=` | Period analytics: readings, energy, events, episodes (2.2) |
| `GET` | `/api/v1/stream/readings` | SSE live readings ~1 Hz, heartbeat every 15 s (2.2) |
| `GET` | `/api/v1/events?...` | Filtered events, id-cursor pagination |
| `PATCH` | `/api/v1/events/{id}` | Acknowledge / resolve (`{"action": ...}`) |
| `GET` | `/api/v1/system/errors` | Last 100 process errors |
| `GET` | `/api/v1/system/database` | DB path, size, tables, schema version |

Out-of-range `limit` values return `422`.

Set `NEXUS_API_KEY` to require an `X-API-Key` header on all
`POST`/`PUT`/`PATCH` endpoints (including the legacy simulation POST);
`GET`s stay public. See `.env.example`.

---

## Tests

Backend (stdlib only — no pytest needed):

```sh
cd backend
.venv/bin/python -m unittest discover -s tests
```

Covers: health checks, pagination limits, 30-day retention pruning, corrupt-database recovery, simulation modes, configuration overrides, the CORS allowlist, settings persistence/validation, the event lifecycle (deduplication, 5-tick resolution, transitions), history aggregation, energy integration from real deltas, and API-key write protection.

Frontend: `npx tsc --noEmit`, `npm run lint`, `npm run build`. (No test framework is installed on purpose — the dashboard is validated via typecheck, lint and build; see Roadmap.)

---

## Production build

```sh
cd frontend
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

---

## Project structure

```text
nexus/
├── start.sh                  # one-command launcher (backend + frontend, LAN-ready)
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, lifespan, CORS, health check
│   │   ├── config.py         # NEXUS_* environment configuration
│   │   ├── api/routes.py     # REST endpoints (legacy /api/*)
│   │   ├── api/v1.py         # REST endpoints (new /api/v1/*)
│   │   ├── api/deps.py       # optional X-API-Key write protection
│   │   ├── engine/
│   │   │   ├── simulator.py  # 1 Hz electrical telemetry simulator
│   │   │   └── diagnostics.py# anomaly detection + recommendations
│   │   ├── services/monitoring.py  # background telemetry loop
│   │   ├── services/settings.py    # persistent system settings
│   │   ├── services/events.py      # event lifecycle + deduplication
│   │   ├── services/aggregation.py # history buckets + stats
│   │   ├── services/errors.py      # in-memory error ring buffer
│   │   ├── database/database.py    # SQLite + retention + corruption recovery
│   │   ├── database/migrations.py  # versioned schema migrations
│   │   └── models/schemas.py
│   ├── tests/                # unittest integration suite
│   ├── requirements.txt      # pinned versions
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── page.tsx      # dashboard
    │   │   ├── error.tsx     # route error boundary
    │   │   └── layout.tsx
    │   ├── lib/api.ts        # API client (runtime-resolved base URL)
    │   └── types/monitoring.ts
    ├── package.json
    └── .env.example
```

---

## Roadmap

- [x] Simulation scenarios switchable from the dashboard
- [x] Automated backend tests
- [x] Environment-based configuration
- [ ] Historical filtering and analytics views
- [ ] Consumption trends and power-quality analysis
- [ ] Statistical / ML anomaly detection
- [ ] Equipment health score and predictive maintenance
- [ ] Exportable monitoring data (CSV)
- [ ] Frontend test suite (when UI logic justifies the dependency)

### Known production gaps (not implemented on purpose for a LAN demo)

- **No authentication** — simulation controls and data are open to anyone on the network. Do not expose to the internet as-is.
- **No rate limiting** on the API.
- **No HTTPS** — LAN demo runs over plain HTTP.
- **SQLite** is ideal for a demo/single node; a multi-user deployment would move to PostgreSQL.

---

## Author

**Lucas Welter Bohrer**

Electrical Engineering Student · Full-Stack Developer · AI & Automation Enthusiast

GitHub: https://github.com/LucaswBohrer

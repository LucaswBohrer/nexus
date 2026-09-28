# NEXUS — Intelligent Electrical Monitoring System

NEXUS is a full-stack software platform for simulating, monitoring and diagnosing electrical systems in real time.

The project combines a virtual electrical telemetry simulator, a diagnostic engine, persistent historical data, event detection and a modern monitoring dashboard.

> **Status:** 🚧 In active development

---

## Overview

NEXUS was designed as a digital electrical monitoring environment without requiring physical hardware.

The system generates simulated electrical measurements and sends them through a FastAPI backend, where the readings are analyzed for abnormal conditions. Measurements and detected events are persisted in SQLite and exposed through a REST API consumed by the Next.js dashboard.

### Core pipeline

```text
Electrical Simulator
        ↓
     FastAPI
        ↓
 Diagnostic Engine
        ↓
      SQLite
        ↓
    REST API
        ↓
 Next.js Dashboard
```

---

## Features

- Real-time electrical telemetry
- Voltage monitoring
- Current monitoring
- Active power calculation
- Power factor monitoring
- Frequency monitoring
- Equipment temperature monitoring
- Automatic anomaly detection
- Severity classification
- Diagnostic recommendations
- Monitoring event generation
- SQLite persistence
- Historical electrical readings
- Real-time dashboard
- Configurable simulation scenarios
- REST API
- Interactive telemetry chart

---

## Simulation Modes

The backend currently supports controlled simulation scenarios for testing the monitoring and diagnostic pipeline:

| Mode | Purpose |
|---|---|
| `normal` | Normal electrical operation |
| `high_voltage` | Simulates excessive voltage |
| `low_voltage` | Simulates low voltage |
| `low_power_factor` | Simulates reduced power factor |
| `high_temperature` | Simulates excessive equipment temperature |
| `multiple_anomalies` | Simulates multiple simultaneous abnormalities |

This allows the system to be tested without physical electrical equipment.

---

## Diagnostic Engine

NEXUS evaluates incoming readings against predefined electrical operating ranges.

Current monitored conditions include:

- Voltage outside 198–242 V
- Frequency outside 59.5–60.5 Hz
- Power factor below 0.80
- Equipment temperature above 70 °C

Detected anomalies generate:

1. An anomaly code
2. A severity level
3. A diagnostic message
4. A maintenance recommendation
5. A persistent monitoring event

---

## Tech Stack

### Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- Recharts
- Lucide React

### Backend

- Python
- FastAPI
- Pydantic
- NumPy
- Pandas
- Scikit-learn

### Database

- SQLite

### Development

- Git
- GitHub
- REST API
- JSON
- Client-server architecture

---

## Project Structure

```text
nexus/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── lib/
│   │   └── types/
│   ├── package.json
│   └── ...
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── database/
│   │   ├── engine/
│   │   ├── models/
│   │   └── services/
│   ├── .venv/
│   └── ...
│
└── docs/
```

---

## API

### Current reading

```http
GET /api/monitoring/current
```

Returns the latest simulated electrical measurement.

### Diagnostics

```http
GET /api/monitoring/diagnostics
```

Returns the current reading together with the diagnostic analysis.

### Historical readings

```http
GET /api/monitoring/history
```

Returns persisted electrical readings from SQLite.

### Monitoring events

```http
GET /api/monitoring/events
```

Returns recently detected monitoring events.

### Simulation mode

```http
POST /api/simulation/mode/{mode}
```

Changes the active simulator scenario.

Example:

```http
POST /api/simulation/mode/high_voltage
```

---

## Running Locally

### Backend

From the project root:

```powershell
cd backend

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install fastapi "uvicorn[standard]" numpy pandas scikit-learn

uvicorn app.main:app --reload --port 8000
```

Backend:

```text
http://localhost:8000
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

### Frontend

Open another terminal:

```powershell
cd frontend

npm install

npm run dev
```

Dashboard:

```text
http://localhost:3000
```

---

## Roadmap

### Phase 1 — Foundation

- [x] Project architecture
- [x] Next.js frontend
- [x] FastAPI backend
- [x] Electrical simulator
- [x] REST API
- [x] Frontend/backend integration

### Phase 2 — Monitoring Core

- [x] Real-time telemetry
- [x] Electrical parameter cards
- [x] Power history chart
- [x] Diagnostic engine
- [x] Anomaly detection
- [x] Severity classification
- [x] Diagnostic recommendations
- [x] SQLite persistence
- [x] Monitoring events

### Phase 3 — Simulation

- [x] Normal operation
- [x] High voltage scenario
- [x] Low voltage scenario
- [x] Low power factor scenario
- [x] High temperature scenario
- [x] Multiple anomaly scenario
- [ ] Simulation controls inside dashboard

### Phase 4 — Analytics

- [ ] Dedicated analytics dashboard
- [ ] Historical filtering
- [ ] Consumption trends
- [ ] Voltage stability analysis
- [ ] Power factor analysis
- [ ] Anomaly frequency analysis
- [ ] Statistical anomaly detection

### Phase 5 — Intelligence

- [ ] Machine learning anomaly detection
- [ ] Equipment health score
- [ ] Predictive maintenance
- [ ] Failure-risk indicators
- [ ] Load behavior analysis
- [ ] Intelligent maintenance recommendations

### Phase 6 — Platform

- [ ] Dedicated monitoring page
- [ ] Events management page
- [ ] Equipment management
- [ ] Configuration panel
- [ ] Reports
- [ ] Exportable monitoring data
- [ ] User authentication

### Phase 7 — Production

- [ ] Automated tests
- [ ] Docker support
- [ ] Production database
- [ ] Environment configuration
- [ ] CI/CD pipeline
- [ ] Cloud deployment
- [ ] Production monitoring

---

## Development Philosophy

NEXUS is intentionally being developed in incremental layers:

```text
Simulation
    ↓
Monitoring
    ↓
Diagnostics
    ↓
Persistence
    ↓
Analytics
    ↓
Machine Learning
    ↓
Predictive Maintenance
    ↓
Production Platform
```

This architecture allows each stage to be tested independently while keeping the project extensible for future intelligent monitoring capabilities.

---

## Project Status

The current implementation already contains the complete core telemetry flow:

```text
Simulator
   ↓
FastAPI
   ↓
Diagnostics
   ↓
SQLite
   ↓
REST API
   ↓
Next.js
   ↓
Dashboard
```

The next major milestone is bringing simulation controls and deeper analytics directly into the web interface.

---

## Author

**Lucas Welter Bohrer**

Electrical Engineering Student · Full-Stack Developer · AI & Automation Enthusiast

GitHub: https://github.com/LucaswBohrer

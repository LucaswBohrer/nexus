"""Deterministic electrical diagnostics (NEXUS 2.1).

The backend is the single source of truth for diagnostic rules: thresholds
come from the settings service (cached, hot-reloadable via the settings
API), and the frontend must NOT duplicate these rules.

Severity is normalized to info/warning/critical. The reading `status` field
keeps the legacy normal/warning/critical values for backwards
compatibility; the API layer maps severities back when serving legacy
clients.
"""

from typing import Any

# Fallback thresholds, used only when the settings service is unavailable
# (e.g. very early startup before the settings table is seeded). They mirror
# the seeded defaults one-to-one.
FALLBACK_THRESHOLDS: dict[str, float] = {
    "voltage_min": 198.0,
    "voltage_max": 242.0,
    "frequency_min": 59.5,
    "frequency_max": 60.5,
    "power_factor_min": 0.80,
    "temperature_max": 70.0,
}


def _load_thresholds() -> dict[str, float]:
    # Lazy import: the engine layer stays decoupled from the service layer,
    # and diagnostics remain usable before settings are seeded.
    try:
        from app.services.settings import get_thresholds

        return get_thresholds()
    except Exception:
        return dict(FALLBACK_THRESHOLDS)


def analyze_reading(
    reading: dict[str, Any], thresholds: dict[str, float] | None = None
) -> dict[str, Any]:
    """Analyze one reading and return status/severity/anomalies/events.

    `thresholds` overrides the settings service (used by tests); when None
    the current settings are used, falling back to FALLBACK_THRESHOLDS.
    """
    t = thresholds if thresholds is not None else _load_thresholds()

    anomalies = []
    recommendations = []
    events = []

    voltage = reading["voltage"]
    frequency = reading["frequency"]
    power_factor = reading["power_factor"]
    temperature = reading["temperature"]
    timestamp = reading["timestamp"]

    if voltage > t["voltage_max"]:
        anomalies.append("HIGH_VOLTAGE")
        recommendation = "Inspect voltage regulation and supply conditions."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "HIGH_VOLTAGE",
            "severity": "warning",
            "message": f"High voltage detected: {voltage:.1f} V",
            "recommendation": recommendation,
            "threshold": t["voltage_max"],
        })
    elif voltage < t["voltage_min"]:
        anomalies.append("LOW_VOLTAGE")
        recommendation = "Check the electrical supply and possible voltage drops."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "LOW_VOLTAGE",
            "severity": "warning",
            "message": f"Low voltage detected: {voltage:.1f} V",
            "recommendation": recommendation,
            "threshold": t["voltage_min"],
        })

    if frequency > t["frequency_max"] or frequency < t["frequency_min"]:
        anomalies.append("FREQUENCY_OUT_OF_RANGE")
        recommendation = "Verify the stability of the electrical frequency."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "FREQUENCY_OUT_OF_RANGE",
            "severity": "warning",
            "message": f"Frequency outside expected range: {frequency:.2f} Hz",
            "recommendation": recommendation,
            "threshold": t["frequency_max"],
        })

    if power_factor < t["power_factor_min"]:
        anomalies.append("LOW_POWER_FACTOR")
        recommendation = "Review reactive power compensation and connected loads."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "LOW_POWER_FACTOR",
            "severity": "warning",
            "message": f"Low power factor detected: {power_factor:.2f}",
            "recommendation": recommendation,
            "threshold": t["power_factor_min"],
        })

    if temperature > t["temperature_max"]:
        anomalies.append("HIGH_TEMPERATURE")
        recommendation = "Inspect equipment cooling and thermal conditions."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "HIGH_TEMPERATURE",
            "severity": "critical",
            "message": f"High equipment temperature detected: {temperature:.1f} °C",
            "recommendation": recommendation,
            "threshold": t["temperature_max"],
        })

    if not anomalies:
        status = "normal"
        severity = "info"
    elif len(anomalies) == 1:
        status = "warning"
        severity = "warning"
    else:
        status = "critical"
        severity = "critical"

    return {
        "status": status,
        "severity": severity,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "events": events,
    }

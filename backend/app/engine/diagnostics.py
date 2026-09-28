from typing import Any


def analyze_reading(reading: dict[str, Any]) -> dict[str, Any]:
    anomalies = []
    recommendations = []
    events = []

    voltage = reading["voltage"]
    frequency = reading["frequency"]
    power_factor = reading["power_factor"]
    temperature = reading["temperature"]
    timestamp = reading["timestamp"]

    if voltage > 242:
        anomalies.append("HIGH_VOLTAGE")
        recommendation = "Inspect voltage regulation and supply conditions."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "HIGH_VOLTAGE",
            "severity": "medium",
            "message": f"High voltage detected: {voltage:.1f} V",
            "recommendation": recommendation,
        })
    elif voltage < 198:
        anomalies.append("LOW_VOLTAGE")
        recommendation = "Check the electrical supply and possible voltage drops."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "LOW_VOLTAGE",
            "severity": "medium",
            "message": f"Low voltage detected: {voltage:.1f} V",
            "recommendation": recommendation,
        })

    if frequency > 60.5 or frequency < 59.5:
        anomalies.append("FREQUENCY_OUT_OF_RANGE")
        recommendation = "Verify the stability of the electrical frequency."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "FREQUENCY_OUT_OF_RANGE",
            "severity": "medium",
            "message": f"Frequency outside expected range: {frequency:.2f} Hz",
            "recommendation": recommendation,
        })

    if power_factor < 0.80:
        anomalies.append("LOW_POWER_FACTOR")
        recommendation = "Review reactive power compensation and connected loads."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "LOW_POWER_FACTOR",
            "severity": "medium",
            "message": f"Low power factor detected: {power_factor:.2f}",
            "recommendation": recommendation,
        })

    if temperature > 70:
        anomalies.append("HIGH_TEMPERATURE")
        recommendation = "Inspect equipment cooling and thermal conditions."
        recommendations.append(recommendation)
        events.append({
            "timestamp": timestamp,
            "event_type": "HIGH_TEMPERATURE",
            "severity": "high",
            "message": f"High equipment temperature detected: {temperature:.1f} °C",
            "recommendation": recommendation,
        })

    if not anomalies:
        status = "normal"
        severity = "low"
    elif len(anomalies) == 1:
        status = "warning"
        severity = "medium"
    else:
        status = "critical"
        severity = "high"

    return {
        "status": status,
        "severity": severity,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "events": events,
    }

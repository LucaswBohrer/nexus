"""Deterministic electrical simulator (NEXUS 2.3).

The simulator is the virtual data source: every telemetry tick asks it
for one reading. Modes describe *deviations from a nominal operating
point*; intensity scales those deviations deterministically.

Design notes:
- Anomaly definitions are centralized in ANOMALY_DEVIATIONS (metric ->
  (deviated mean, sigma)). No magic numbers are scattered through
  generate_reading().
- intensity is a percentage 0-200. The deviated mean for a metric is
      nominal + (target - nominal) * intensity / 100
  so 100% reproduces the historical (2.1/2.2) behaviour exactly,
  0% collapses to the nominal point and 200% doubles the deviation.
- A mode maps to a list of anomaly keys (MODE_ANOMALIES); the optional
  composer `anomalies` list adds more. The effective set is the
  order-preserving deduplication of both. If two anomalies deviate the
  same metric, the later one wins (documented; combining opposites is
  user error, not a crash).
- sensor_failure freezes the last reading (values stop updating, the
  reading is flagged ``stale=True``). It cannot be combined with other
  anomalies: a frozen sensor dominates everything else, so such a
  combination is rejected as impossible.
- Physical clamps and the active_power = V*I*PF/1000 chain are always
  applied, at every intensity. No NaN/inf can escape: intensity is
  validated finite in [0, 200].
"""

import math
import numbers
import random
from datetime import datetime, timezone
from typing import Any

# Nominal (baseline) operating point. All deviations are offsets from here.
NOMINAL: dict[str, float] = {
    "voltage": 220.0,
    "current": 12.0,
    "frequency": 60.0,
    "power_factor": 0.93,
    "temperature": 42.0,
}

# Baseline noise (sigma) per metric, unchanged since 2.1.
BASELINE_SIGMA: dict[str, float] = {
    "voltage": 2.0,
    "current": 1.2,
    "frequency": 0.05,
    "power_factor": 0.025,
    "temperature": 3.0,
}

# Centralized anomaly definitions: metric -> (deviated mean at 100%, sigma).
ANOMALY_DEVIATIONS: dict[str, dict[str, tuple[float, float]]] = {
    "high_voltage": {"voltage": (250.0, 2.0)},
    "low_voltage": {"voltage": (190.0, 2.0)},
    "low_power_factor": {"power_factor": (0.68, 0.03)},
    "high_temperature": {"temperature": (78.0, 3.0)},
    "overload": {"current": (28.0, 1.5)},
}

# Mode -> anomaly keys applied by that mode. The composer `anomalies`
# argument extends this list.
MODE_ANOMALIES: dict[str, list[str]] = {
    "normal": [],
    "high_voltage": ["high_voltage"],
    "low_voltage": ["low_voltage"],
    "low_power_factor": ["low_power_factor"],
    "high_temperature": ["high_temperature"],
    "multiple_anomalies": ["high_voltage", "low_power_factor", "high_temperature"],
    "sensor_failure": ["sensor_failure"],
    "oscillation": ["oscillation"],
    "overload": ["overload"],
}

VALID_MODES = frozenset(MODE_ANOMALIES)
VALID_ANOMALIES = frozenset(
    list(ANOMALY_DEVIATIONS) + ["sensor_failure", "oscillation"]
)

# Oscillation: deterministic sine wave on voltage, one full period every
# 24 ticks (~24 s). Amplitude at 100% intensity; scaled by intensity.
OSCILLATION_PERIOD_TICKS = 24
OSCILLATION_AMPLITUDE_V = 15.0

# Intensity bounds (percent).
INTENSITY_MIN = 0.0
INTENSITY_MAX = 200.0


class SimulationError(ValueError):
    """Invalid simulation scenario (surfaced as HTTP 422 / legacy 400)."""


def _validate_intensity(intensity: Any) -> float:
    if isinstance(intensity, bool) or not isinstance(intensity, numbers.Real):
        raise SimulationError(
            f"intensity must be a number in [{INTENSITY_MIN}, {INTENSITY_MAX}], "
            f"got {intensity!r}"
        )
    value = float(intensity)
    if not math.isfinite(value) or not (INTENSITY_MIN <= value <= INTENSITY_MAX):
        raise SimulationError(
            f"intensity must be a finite number in [{INTENSITY_MIN}, "
            f"{INTENSITY_MAX}], got {intensity!r}"
        )
    return value


def _validate_anomalies(anomalies: Any) -> list[str]:
    if anomalies is None:
        return []
    if not isinstance(anomalies, (list, tuple)):
        raise SimulationError(
            f"anomalies must be a list of anomaly names, got {anomalies!r}"
        )
    cleaned: list[str] = []
    for entry in anomalies:
        if entry not in VALID_ANOMALIES:
            raise SimulationError(
                f"Unknown anomaly {entry!r}. Valid: {sorted(VALID_ANOMALIES)}"
            )
        cleaned.append(entry)
    return cleaned


class ElectricalSimulator:
    def __init__(self):
        self.voltage_base = NOMINAL["voltage"]
        self.frequency_base = NOMINAL["frequency"]
        self.mode = "normal"
        self.intensity = 100.0
        self.anomalies: list[str] = []
        # Tick counter driving the deterministic oscillation phase.
        self._tick_n = 0
        # Frozen reading used by sensor_failure (values stop updating).
        self._frozen: dict[str, Any] | None = None

    # -- scenario control -------------------------------------------------

    def set_mode(self, mode: str):
        """Legacy simple mode switch: intensity 100%, no composer anomalies."""
        self.apply_scenario(mode, intensity=100.0, anomalies=[])

    def apply_scenario(
        self,
        mode: str,
        intensity: float = 100.0,
        anomalies: list[str] | tuple[str, ...] | None = None,
    ):
        """Apply a full simulation scenario, validated.

        Raises SimulationError for unknown modes, out-of-range intensity,
        unknown anomalies, or impossible combinations.
        """
        if mode not in VALID_MODES:
            raise SimulationError(
                f"Invalid simulation mode: {mode!r}. "
                f"Valid: {sorted(VALID_MODES)}"
            )
        intensity_value = _validate_intensity(intensity)
        anomaly_list = _validate_anomalies(anomalies)

        effective = self._effective_anomalies(mode, anomaly_list)
        if "sensor_failure" in effective and len(effective) > 1:
            raise SimulationError(
                "sensor_failure cannot be combined with other anomalies: "
                "a frozen sensor dominates every other deviation"
            )

        self.mode = mode
        self.intensity = intensity_value
        self.anomalies = anomaly_list
        if "sensor_failure" not in effective:
            self._frozen = None

    def reset_scenario(self):
        """Back to a clean normal scenario."""
        self.mode = "normal"
        self.intensity = 100.0
        self.anomalies = []
        self._frozen = None

    def get_scenario(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "intensity": self.intensity,
            "anomalies": list(self.anomalies),
            "effective_anomalies": self._effective_anomalies(
                self.mode, self.anomalies
            ),
        }

    @staticmethod
    def _effective_anomalies(mode: str, anomalies: list[str]) -> list[str]:
        seen: list[str] = []
        for key in MODE_ANOMALIES[mode] + anomalies:
            if key not in seen:
                seen.append(key)
        return seen

    # -- reading generation -----------------------------------------------

    def _deviated_mean(self, metric: str) -> tuple[float, float]:
        """(mean, sigma) for a metric under the current scenario.

        Each anomaly moves the mean away from nominal proportionally to
        intensity; at 100% the historical target mean is reproduced
        exactly.
        """
        nominal = NOMINAL[metric]
        mean = nominal
        sigma = BASELINE_SIGMA[metric]
        for key in self._effective_anomalies(self.mode, self.anomalies):
            spec = ANOMALY_DEVIATIONS.get(key)
            if spec and metric in spec:
                target, anomaly_sigma = spec[metric]
                mean = nominal + (target - nominal) * (self.intensity / 100.0)
                sigma = anomaly_sigma
        return mean, sigma

    def _frozen_reading(self) -> dict[str, Any]:
        """sensor_failure: values stop updating; the reading is flagged stale.

        The acquisition timestamp keeps advancing (the poller is alive) but
        every electrical value is frozen, so the failure is unmistakable:
        zero variance plus an explicit ``stale`` marker. No fake-normal
        random values are generated.
        """
        if self._frozen is None:
            base = self._baseline_sample()
            base["status"] = "normal"
            self._frozen = base
        reading = dict(self._frozen)
        reading["timestamp"] = datetime.now(timezone.utc)
        reading["stale"] = True
        return reading

    def _baseline_sample(self) -> dict[str, Any]:
        voltage_mean, voltage_sigma = self._deviated_mean("voltage")
        current_mean, current_sigma = self._deviated_mean("current")
        frequency_mean, frequency_sigma = self._deviated_mean("frequency")
        pf_mean, pf_sigma = self._deviated_mean("power_factor")
        temp_mean, temp_sigma = self._deviated_mean("temperature")

        voltage = random.gauss(voltage_mean, voltage_sigma)
        current = random.gauss(current_mean, current_sigma)
        frequency = random.gauss(frequency_mean, frequency_sigma)
        power_factor = random.gauss(pf_mean, pf_sigma)
        temperature = random.gauss(temp_mean, temp_sigma)

        effective = self._effective_anomalies(self.mode, self.anomalies)
        if "oscillation" in effective:
            # Deterministic sine wave on voltage; amplitude scales with
            # intensity. Predictable by construction: same tick offset
            # from scenario start always yields the same phase.
            amplitude = OSCILLATION_AMPLITUDE_V * (self.intensity / 100.0)
            phase = 2 * math.pi * (self._tick_n / OSCILLATION_PERIOD_TICKS)
            voltage = NOMINAL["voltage"] + amplitude * math.sin(phase)

        voltage = round(voltage, 2)
        current = round(max(current, 0.1), 2)
        frequency = round(frequency, 3)
        power_factor = round(min(max(power_factor, 0.5), 1.0), 3)
        temperature = round(max(temperature, 15.0), 2)

        active_power = round((voltage * current * power_factor) / 1000, 3)

        return {
            # NEXUS 2.1: all new timestamps are timezone-aware UTC. The
            # migration layer converts legacy America/Sao_Paulo values.
            "timestamp": datetime.now(timezone.utc),
            "voltage": voltage,
            "current": current,
            "frequency": frequency,
            "power_factor": power_factor,
            "active_power": active_power,
            "temperature": temperature,
            "status": "normal",
        }

    def generate_reading(self):
        self._tick_n += 1
        if "sensor_failure" in self._effective_anomalies(
            self.mode, self.anomalies
        ):
            return self._frozen_reading()
        self._frozen = None
        return self._baseline_sample()


simulator = ElectricalSimulator()

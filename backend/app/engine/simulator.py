import random
from datetime import datetime


class ElectricalSimulator:
    def __init__(self):
        self.voltage_base = 220.0
        self.frequency_base = 60.0
        self.mode = "normal"

    def set_mode(self, mode: str):
        allowed_modes = {
            "normal",
            "high_voltage",
            "low_voltage",
            "low_power_factor",
            "high_temperature",
            "multiple_anomalies",
        }

        if mode not in allowed_modes:
            raise ValueError(f"Invalid simulation mode: {mode}")

        self.mode = mode

    def generate_reading(self):
        voltage = random.gauss(self.voltage_base, 2.0)
        current = random.gauss(12.0, 1.2)
        frequency = random.gauss(self.frequency_base, 0.05)
        power_factor = random.gauss(0.93, 0.025)
        temperature = random.gauss(42.0, 3.0)

        if self.mode == "high_voltage":
            voltage = random.gauss(250.0, 2.0)
        elif self.mode == "low_voltage":
            voltage = random.gauss(190.0, 2.0)
        elif self.mode == "low_power_factor":
            power_factor = random.gauss(0.68, 0.03)
        elif self.mode == "high_temperature":
            temperature = random.gauss(78.0, 3.0)
        elif self.mode == "multiple_anomalies":
            voltage = random.gauss(250.0, 2.0)
            power_factor = random.gauss(0.68, 0.03)
            temperature = random.gauss(78.0, 3.0)

        voltage = round(voltage, 2)
        current = round(max(current, 0.1), 2)
        frequency = round(frequency, 3)
        power_factor = round(min(max(power_factor, 0.5), 1.0), 3)
        temperature = round(max(temperature, 15.0), 2)

        active_power = round(
            (voltage * current * power_factor) / 1000,
            3,
        )

        return {
            "timestamp": datetime.now(),
            "voltage": voltage,
            "current": current,
            "frequency": frequency,
            "power_factor": power_factor,
            "active_power": active_power,
            "temperature": temperature,
            "status": "normal",
        }


simulator = ElectricalSimulator()

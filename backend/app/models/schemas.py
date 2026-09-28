from datetime import datetime

from pydantic import BaseModel, Field


class ElectricalReading(BaseModel):
    timestamp: datetime

    voltage: float = Field(..., description="Voltage in volts")
    current: float = Field(..., description="Current in amperes")
    frequency: float = Field(..., description="Frequency in hertz")
    power_factor: float = Field(..., description="Power factor")
    active_power: float = Field(..., description="Active power in kilowatts")
    temperature: float = Field(..., description="Equipment temperature in Celsius")

    status: str = "normal"
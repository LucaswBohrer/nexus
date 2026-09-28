from datetime import datetime
<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
from pydantic import BaseModel, Field


class ElectricalReading(BaseModel):
    timestamp: datetime
<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
    voltage: float = Field(..., description="Voltage in volts")
    current: float = Field(..., description="Current in amperes")
    frequency: float = Field(..., description="Frequency in hertz")
    power_factor: float = Field(..., description="Power factor")
    active_power: float = Field(..., description="Active power in kilowatts")
    temperature: float = Field(..., description="Equipment temperature in Celsius")
<<<<<<< HEAD

    status: str = "normal"
=======
    status: str = "normal"
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac

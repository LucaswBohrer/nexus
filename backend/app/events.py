from datetime import datetime
from pydantic import BaseModel


class MonitoringEvent(BaseModel):
    id: int | None = None
    timestamp: datetime
    event_type: str
    severity: str
    message: str
    recommendation: str
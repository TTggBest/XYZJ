from datetime import date, datetime

from pydantic import BaseModel


class FeishuSyncResult(BaseModel):
    sync_type: str
    environment: str
    rows_read: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    latest_date: date | None
    completed_at: datetime

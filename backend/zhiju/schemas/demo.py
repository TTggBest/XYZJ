from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoDataImportRequest(BaseModel):
    work_rows: list[dict[str, str | None]] = Field(min_length=1, max_length=20)
    task_rows: list[dict[str, str | None]] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_pairs(self):
        if len(self.work_rows) != len(self.task_rows):
            raise ValueError("工单表与任务表样本行数必须一致")
        return self


class DemoDataBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_code: str
    source_label: str
    row_count: int
    start_date: date
    end_date: date
    status: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DemoDataStatusRead(BaseModel):
    active: bool
    batch: DemoDataBatchRead | None
    entity_counts: dict[str, int]

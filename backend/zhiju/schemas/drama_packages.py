from datetime import date,datetime
from pydantic import BaseModel,Field
from zhiju.schemas.production import PackageOutputsRead


class DramaPackagePreviewImage(BaseModel):
    aspect_ratio: str
    asset_id: str | None


class DramaPackageCoverPreview(BaseModel):
    variant_number: int
    localized_title: str
    chinese_translation: str | None
    covers: list[DramaPackagePreviewImage]


class DramaPackageRecord(BaseModel):
    package_id: str
    channel_id: str
    channel_name: str
    channel_operational_name: str | None
    language: str | None
    language_name: str | None
    production_date: date
    version_number: int
    status: str
    created_at: datetime
    ready_at: datetime | None
    cover_previews: list[DramaPackageCoverPreview] = Field(default_factory=list)


class DramaPackageHistory(BaseModel):
    drama_id: str
    drama_name: str
    drama_code: str
    package_count: int
    channel_count: int
    items: list[DramaPackageRecord]


class DramaPackageDetail(BaseModel):
    record: DramaPackageRecord
    outputs: PackageOutputsRead

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AllowedFileType = Literal["pdf", "txt", "docx"]


class CreateUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=3, max_length=512)
    file_type: AllowedFileType
    file_size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        lowered = value.lower()
        if "/" in lowered or "\\" in lowered:
            raise ValueError("filename must not contain path separators")
        return value


class CreateUploadUrlResponse(BaseModel):
    document_id: str
    upload_url: str
    object_key: str
    expires_in_seconds: int = 900


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: Literal["pending", "processing", "indexed", "failed"]
    error_message: str | None = None
    updated_at: datetime | None = None

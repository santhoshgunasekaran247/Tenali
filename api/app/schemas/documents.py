import base64
import binascii
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 5
EntityType = Literal["purchase", "business_payment"]


class AttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=200)
    mime_type: Literal["application/pdf", "image/jpeg", "image/png", "image/webp"]
    data_base64: str = Field(min_length=1, max_length=4 * ((MAX_FILE_BYTES + 2) // 3))

    @model_validator(mode="after")
    def validate_file(self):
        self.file_name = "".join(character for character in self.file_name.replace("\\", "/").rsplit("/", 1)[-1]
                                 if ord(character) >= 32 and ord(character) != 127).strip()
        if not self.file_name:
            raise ValueError("File name is required")
        try:
            content = base64.b64decode(self.data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid file encoding") from exc
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError("Each attachment must be non-empty and no larger than 5 MB")
        signatures = {
            "application/pdf": (b"%PDF-", (".pdf",)),
            "image/jpeg": (b"\xff\xd8\xff", (".jpg", ".jpeg")),
            "image/png": (b"\x89PNG\r\n\x1a\n", (".png",)),
            "image/webp": (b"RIFF", (".webp",)),
        }
        signature, extensions = signatures[self.mime_type]
        if not content.startswith(signature) or not self.file_name.lower().endswith(extensions):
            raise ValueError("File contents, extension and type must match PDF, JPEG, PNG or WebP")
        if self.mime_type == "image/webp" and content[8:12] != b"WEBP":
            raise ValueError("Invalid WebP file")
        return self


class AttachmentUpload(BaseModel):
    items: list[AttachmentCreate] = Field(min_length=1, max_length=MAX_ATTACHMENTS)


class AttachmentOut(BaseModel):
    id: UUID
    file_name: str
    mime_type: str
    file_size: int
    created_at: datetime


class AttachmentListResponse(BaseModel):
    items: list[AttachmentOut]
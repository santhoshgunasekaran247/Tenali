from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class PartyOut(BaseModel):
    id: UUID
    company_id: UUID
    party_type: str
    nickname: str | None = None
    legal_name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool


class PartyCreate(BaseModel):
    party_type: str
    legal_name: str
    nickname: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None


class PartyUpdate(BaseModel):
    party_type: str | None = None
    legal_name: str | None = None
    nickname: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool | None = None


class PartyListResponse(BaseModel):
    items: list[PartyOut]

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.auth import administrator, identity_db
from app.dependencies import get_db
from app.schemas.parties import PartyCreate, PartyListResponse, PartyOut, PartyUpdate
from app.services import shopper_federation
from app.services.parties_service import PartiesService

router = APIRouter()


class CustomerLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_party_id: UUID


@router.get("/online-customers")
def list_online_customers(
    identity=Depends(administrator),
    db: Session = Depends(identity_db),
):
    rows = db.execute(
        text(
            """
            select id, email, display_name, phone, customer_party_id
            from shopper_accounts
            where company_id = :company_id and is_active
            order by created_at desc, id
            """
        ),
        {"company_id": str(identity["company_id"])},
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@router.post("/online-customers/{shopper_id}/link")
def link_online_customer(
    shopper_id: UUID,
    payload: CustomerLink,
    identity=Depends(administrator),
    db: Session = Depends(identity_db),
):
    return shopper_federation.link_customer(
        db,
        str(identity["company_id"]),
        str(shopper_id),
        str(payload.customer_party_id),
        str(identity["user_id"]),
    )


@router.get("", response_model=PartyListResponse)
def list_parties(
    company_id: str | None = None,
    search: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    service = PartiesService(db)
    return service.list(company_id=company_id, search=search, active_only=active_only)


@router.post("", response_model=PartyOut, status_code=201)
def create_party(
    payload: PartyCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PartiesService(db)
    return service.create(company_id=company_id, payload=payload)


@router.patch("/{party_id}", response_model=PartyOut)
def update_party(
    party_id: str,
    payload: PartyUpdate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = PartiesService(db)
    return service.update(party_id=party_id, payload=payload, company_id=company_id)

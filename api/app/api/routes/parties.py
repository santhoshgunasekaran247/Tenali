from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.parties import PartyCreate, PartyListResponse, PartyOut, PartyUpdate
from app.services.parties_service import PartiesService

router = APIRouter()


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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.auth import administrator, identity_db
from app.dependencies import get_db
from app.schemas.parties import PartyCreate, PartyListResponse, PartyOut, PartyUpdate
from app.services import shopper_federation
from app.services.parties_service import PartiesService
from app.services.pagination import cursor_page, decode_cursor

router = APIRouter()


class CustomerLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_party_id: UUID


class PagedPartyListResponse(PartyListResponse):
    next_cursor: str | None = None


@router.get("/online-customers")
def list_online_customers(
    search: str | None = Query(default=None, max_length=300),
    page_size: int | None = Query(default=None, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1000),
    identity=Depends(administrator),
    db: Session = Depends(identity_db),
):
    if cursor and page_size is None:
        raise HTTPException(status_code=422, detail="Cursor requires page_size")
    query = """
        select id, email, display_name, phone, customer_party_id, created_at
        from shopper_accounts
        where company_id = :company_id and is_active
    """
    params = {"company_id": str(identity["company_id"])}
    if search and search.strip():
        query += """ and (strpos(lower(coalesce(display_name, '')), lower(:search)) > 0
                     or strpos(lower(coalesce(email, '')), lower(:search)) > 0
                     or strpos(lower(coalesce(phone, '')), lower(:search)) > 0)"""
        params["search"] = search.strip()
    if page_size is not None:
        boundary = decode_cursor(cursor, ("created_at", "id"))
        if boundary:
            query += """ and (created_at < cast(:cursor_created_at as timestamptz)
                       or (created_at = cast(:cursor_created_at as timestamptz) and id > cast(:cursor_id as uuid)))"""
            params.update(cursor_created_at=boundary["created_at"], cursor_id=boundary["id"])
    query += " order by created_at desc, id"
    if page_size is not None:
        query += " limit :limit"
        params["limit"] = page_size + 1
    rows = db.execute(
        text(query), params,
    ).mappings().all()
    result = cursor_page(rows, page_size, ("created_at", "id")) if page_size is not None else {"items": [dict(row) for row in rows]}
    for item in result["items"]:
        item.pop("created_at")
    return result


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


@router.get("", response_model=PagedPartyListResponse, response_model_exclude_unset=True)
def list_parties(
    company_id: str | None = None,
    search: str | None = Query(default=None, max_length=300),
    active_only: bool = True,
    page_size: int | None = Query(default=None, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(status_code=422, detail="Cursor requires page_size")
    service = PartiesService(db)
    return service.list(company_id=company_id, search=search, active_only=active_only, page_size=page_size, cursor=cursor)


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

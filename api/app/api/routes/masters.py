from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.masters import HsnMasterCreate, HsnMasterListResponse, HsnMasterOut, HsnMasterUpdate
from app.services.masters_service import MastersService

router = APIRouter()


@router.get("/hsn", response_model=HsnMasterListResponse)
def list_hsn(company_id: UUID | None = None, active_only: bool = True,
             search: str | None = Query(default=None, max_length=300), db: Session = Depends(get_db)):
    return MastersService(db).list_hsn(str(company_id) if company_id else None, active_only, search)


@router.post("/hsn", response_model=HsnMasterOut, status_code=201)
def create_hsn(payload: HsnMasterCreate, company_id: UUID | None = None, db: Session = Depends(get_db)):
    return MastersService(db).create_hsn(payload, str(company_id) if company_id else None)


@router.put("/hsn/{master_id}", response_model=HsnMasterOut)
def update_hsn(master_id: UUID, payload: HsnMasterUpdate, company_id: UUID | None = None,
               db: Session = Depends(get_db)):
    return MastersService(db).update_hsn(str(master_id), payload, str(company_id) if company_id else None)
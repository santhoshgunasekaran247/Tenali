from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.stores import StoreInput, StoreListResponse, StoreOut
from app.services.stores_service import StoresService

router = APIRouter()


def stores_service(company_id: UUID | None = None, db: Session = Depends(get_db)) -> StoresService:
    return StoresService(db, str(company_id) if company_id else None)


@router.get("", response_model=StoreListResponse)
def list_stores(include_inactive: bool = True, service: StoresService = Depends(stores_service)):
    return service.list_stores(include_inactive)


@router.post("", response_model=StoreOut, status_code=201)
def create_store(payload: StoreInput, service: StoresService = Depends(stores_service)):
    return service.create_store(payload)


@router.put("/{store_id}", response_model=StoreOut)
def update_store(store_id: UUID, payload: StoreInput, service: StoresService = Depends(stores_service)):
    return service.update_store(str(store_id), payload)


@router.post("/{store_id}/default", response_model=StoreOut)
def set_default(store_id: UUID, service: StoresService = Depends(stores_service)):
    return service.set_default(str(store_id))

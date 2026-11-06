from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.transaction_deletion import TransactionDeletionService

router = APIRouter()


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: str = Field(min_length=1, max_length=40)
    id: UUID | None = None
    cascade: bool = False
    token: str = Field(min_length=64, max_length=64)
    confirm_text: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


def deletion_service(db: Session = Depends(get_db)) -> TransactionDeletionService:
    # Destructive: the workspace always comes from the signed-in identity, never from the request.
    company_id = (db.info.get("tenant_context") or {}).get("company_id")
    if not company_id:
        raise HTTPException(401, "Sign in to your workspace")
    return TransactionDeletionService(db, str(company_id))


@router.get("")
def history(service: TransactionDeletionService = Depends(deletion_service)):
    return service.history()


@router.get("/preview")
def preview(kind: str, id: UUID | None = None, cascade: bool = False,
            service: TransactionDeletionService = Depends(deletion_service)):
    return service.preview(kind, str(id) if id else None, cascade)


@router.post("")
def delete(payload: DeletionRequest, service: TransactionDeletionService = Depends(deletion_service)):
    return service.delete(payload.kind, str(payload.id) if payload.id else None, payload.token,
                          payload.confirm_text, payload.reason, payload.cascade)

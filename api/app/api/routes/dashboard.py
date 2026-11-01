from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("")
def dashboard(month: date | None = None, store_id: UUID | None = None, db: Session = Depends(get_db)):
    return DashboardService(db).summary(month, str(store_id) if store_id else None)

from datetime import date
from uuid import UUID

from fastapi import APIRouter,Depends,Query
from sqlalchemy import text
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.gst_reconciliation import reconcile_2b
from app.services.company_service import CompanyService

router=APIRouter()


@router.get('/audit-events')
def audit_events(company_id:UUID|None=None,from_date:date|None=None,to_date:date|None=None,
                 limit:int=Query(default=100,ge=1,le=500),offset:int=Query(default=0,ge=0),db:Session=Depends(get_db)):
    company=CompanyService(db).get(str(company_id) if company_id else None)
    rows=db.execute(text("""select id,action,entity_type,entity_id,old_value,new_value,created_at,user_id from audit_events
        where company_id=:company and (cast(:from_date as date) is null or created_at::date>=:from_date)
        and (cast(:to_date as date) is null or created_at::date<=:to_date)
        order by created_at desc,id desc limit :limit offset :offset"""),
        {'company':str(company['id']),'from_date':from_date,'to_date':to_date,'limit':limit,'offset':offset}).mappings().all()
    return {'items':[dict(row) for row in rows]}


class ReconciliationInput(BaseModel):
    csv_text:str=Field(max_length=5_000_000)
    from_date:date
    to_date:date


@router.post('/gstr2b/reconcile')
def reconcile(payload:ReconciliationInput,company_id:UUID|None=None,db:Session=Depends(get_db)):
    company=CompanyService(db).get(str(company_id) if company_id else None)
    return reconcile_2b(db,str(company['id']),payload.csv_text,payload.from_date,payload.to_date)
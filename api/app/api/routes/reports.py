from datetime import date
from uuid import UUID

from fastapi import APIRouter,Depends,Query,HTTPException
from sqlalchemy import text
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.gst_reconciliation import reconcile_2b
from app.services.company_service import CompanyService
from app.services.pagination import cursor_page, decode_cursor

router=APIRouter()


@router.get('/audit-events')
def audit_events(company_id:UUID|None=None,from_date:date|None=None,to_date:date|None=None,
                 limit:int=Query(default=100,ge=1,le=500),offset:int=Query(default=0,ge=0),
                 page_size:int|None=Query(default=None,ge=1,le=100),cursor:str|None=Query(default=None,max_length=1000),
                 db:Session=Depends(get_db)):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    if page_size is not None and from_date and to_date and from_date > to_date:
        raise HTTPException(422, "from_date cannot be after to_date")
    company=CompanyService(db).get(str(company_id) if company_id else None)
    query="""select id,action,entity_type,entity_id,old_value,new_value,created_at,user_id,actor_user_id from audit_events
        where company_id=:company"""
    params={'company':str(company['id']),'from_date':from_date,'to_date':to_date,'limit':limit,'offset':offset}
    if page_size is not None:
        query += """ and (cast(:from_date as date) is null or created_at >= (cast(:from_date as timestamp) at time zone 'Asia/Kolkata'))
            and (cast(:to_date as date) is null or created_at < (cast((cast(:to_date as date) + 1) as timestamp) at time zone 'Asia/Kolkata'))"""
        boundary=decode_cursor(cursor, ("created_at", "id"))
        if boundary:
            query += " and (created_at,id) < (cast(:created_at as timestamptz),cast(:id as uuid))"
            params.update(boundary)
        params['limit']=page_size+1
        query += " order by created_at desc,id desc limit :limit"
    else:
        query += """ and (cast(:from_date as date) is null or created_at::date>=:from_date)
            and (cast(:to_date as date) is null or created_at::date<=:to_date)"""
        query += " order by created_at desc,id desc limit :limit offset :offset"
    rows=db.execute(text(query),params).mappings().all()
    if page_size is not None:
        return cursor_page(rows,page_size,("created_at","id"))
    return {'items':[dict(row) for row in rows]}


class ReconciliationInput(BaseModel):
    csv_text:str=Field(max_length=5_000_000)
    from_date:date
    to_date:date


@router.post('/gstr2b/reconcile')
def reconcile(payload:ReconciliationInput,company_id:UUID|None=None,db:Session=Depends(get_db)):
    company=CompanyService(db).get(str(company_id) if company_id else None)
    return reconcile_2b(db,str(company['id']),payload.csv_text,payload.from_date,payload.to_date)
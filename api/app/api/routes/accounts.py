from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.accounts import (
    AccountCreate,
    AccountTallyResponse,
    AuditJournalResponse,
    AccountListResponse,
    AccountOut,
    BusinessPaymentCreate,
    BusinessPaymentOut,
    AccountTransactionCreate,
    AccountTransactionListResponse,
    AccountTransactionOut,
    AccountUpdate,
    PeriodLockCreate,
    PeriodLockListResponse,
    PeriodLockOut,
    PeriodLockReopen,
    TransactionReverseCreate,
    TransactionReverseOut,
)
from app.services.accounts_service import AccountsService

router = APIRouter()


@router.get("", response_model=AccountListResponse)
def list_accounts(
    company_id: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.list_accounts(company_id=company_id, active_only=active_only)


@router.post("", response_model=AccountOut, status_code=201)
def create_account(
    payload: AccountCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.create_account(company_id=company_id, payload=payload)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: str,
    payload: AccountUpdate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.update_account(account_id=account_id, company_id=company_id, payload=payload)


@router.get("/transactions", response_model=AccountTransactionListResponse)
def list_transactions(
    company_id: str | None = None,
    limit: int = 100,
    account_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    source_type: str | None = None,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    service = AccountsService(db)
    return service.list_transactions(
        company_id=company_id,
        limit=limit,
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
        category=category,
        source_type=source_type,
        page_size=page_size, cursor=cursor,
    )


@router.get("/tally", response_model=AccountTallyResponse)
def account_tally(
    company_id: str | None = None,
    as_of: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.account_tally(
        company_id=company_id,
        as_of=as_of,
        include_inactive=include_inactive,
    )


@router.get("/journal", response_model=AuditJournalResponse)
def extract_audit_journal(
    company_id: str | None = None,
    period: str = "daily",
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    source_type: str | None = None,
    limit: int = 2000,
    page_size: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = Depends(get_db),
):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    service = AccountsService(db)
    return service.list_audit_journal(
        company_id=company_id,
        period=period,
        from_date=from_date,
        to_date=to_date,
        category=category,
        source_type=source_type,
        limit=limit,
        page_size=page_size,
        cursor=cursor,
    )


@router.post("/transactions", response_model=AccountTransactionOut, status_code=201)
def create_transaction(
    payload: AccountTransactionCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.create_transaction(company_id=company_id, payload=payload)


@router.post("/transactions/{transaction_id}/reverse", response_model=TransactionReverseOut)
def reverse_transaction(
    transaction_id: str,
    payload: TransactionReverseCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.reverse_transaction(
        transaction_id=transaction_id,
        company_id=company_id,
        payload=payload,
    )


@router.post("/business-payments", response_model=BusinessPaymentOut, status_code=201)
def create_business_payment(
    payload: BusinessPaymentCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.create_business_payment(company_id=company_id, payload=payload)


@router.get("/business-payments", response_model=AccountTransactionListResponse)
def list_business_payments(company_id: str | None = None, limit: int = 100,
                           page_size: int | None = Query(None, ge=1, le=100),
                           cursor: str | None = Query(None, max_length=1000),
                           from_date: str | None = None, to_date: str | None = None,
                           db: Session = Depends(get_db)):
    if cursor and page_size is None:
        raise HTTPException(422, "page_size is required with cursor")
    return AccountsService(db).list_transactions(company_id=company_id, limit=limit, business_only=True,
                                                 page_size=page_size, cursor=cursor, from_date=from_date, to_date=to_date)


@router.get("/period-locks", response_model=PeriodLockListResponse)
def list_period_locks(
    company_id: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.list_period_locks(company_id=company_id, include_inactive=include_inactive)


@router.post("/period-locks", response_model=PeriodLockOut, status_code=201)
def close_period(
    payload: PeriodLockCreate,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.close_period(company_id=company_id, payload=payload)


@router.post("/period-locks/{lock_id}/reopen", response_model=PeriodLockOut)
def reopen_period(
    lock_id: str,
    payload: PeriodLockReopen,
    company_id: str | None = None,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    return service.reopen_period(lock_id=lock_id, company_id=company_id, payload=payload)


@router.get("/transactions/export")
def export_transactions_csv(
    company_id: str | None = None,
    limit: int = 1000,
    account_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    source_type: str | None = None,
    full: bool = False,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    if full:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        output = service.export_full_csv(company_id, journal=False, account_id=account_id, from_date=from_date,
                                         to_date=to_date, category=category, source_type=source_type)
        return csv_file_response(output, "account_transactions.csv")
    csv_data = service.export_transactions_csv(
        company_id=company_id,
        limit=limit,
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
        category=category,
        source_type=source_type,
    )
    file_name = f"account_transactions_{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/journal/export")
def export_journal_csv(
    company_id: str | None = None,
    period: str = "daily",
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    source_type: str | None = None,
    limit: int = 5000,
    full: bool = False,
    db: Session = Depends(get_db),
):
    service = AccountsService(db)
    if full:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        output = service.export_full_csv(company_id, journal=True, period=period, from_date=from_date,
                                         to_date=to_date, category=category, source_type=source_type)
        return csv_file_response(output, "audit_journal.csv")
    csv_data = service.export_journal_csv(
        company_id=company_id,
        period=period,
        from_date=from_date,
        to_date=to_date,
        category=category,
        source_type=source_type,
        limit=limit,
    )
    file_name = f"audit_journal_{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def csv_file_response(output, filename: str) -> StreamingResponse:
    def chunks():
        try:
            while chunk := output.read(65536):
                yield chunk
        finally:
            output.close()
    return StreamingResponse(chunks(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})

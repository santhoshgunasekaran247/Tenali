from datetime import date

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIXES = {"invoice": "INV", "purchase": "PUR"}


def next_document_number(db: Session, company_id: str, store: dict, kind: str, document_date: date) -> str:
    """Monthly store counter: I<STOREID>YYYYMMDDNNNNN or PUR-<STORE>-YYYYMM-NNNNN.

    The upsert takes a row lock, so concurrent postings in one store serialize on the counter.
    """
    number = db.execute(
        text(
            """
            insert into document_sequences (company_id, store_id, kind, year, month, last_number)
            values (:company, :store, :kind, :year, :month, 1)
            on conflict (company_id, store_id, kind, year, month)
            do update set last_number = document_sequences.last_number + 1
            returning last_number
            """
        ),
        {"company": company_id, "store": str(store["id"]), "kind": kind,
         "year": document_date.year, "month": document_date.month},
    ).scalar_one()
    if kind == "invoice":
        if int(number) > 99999:
            raise HTTPException(422, "This store has reached the monthly invoice limit of 99999; a 16-character invoice number cannot be generated.")
        return f"I{store['invoice_code']}{document_date:%Y%m%d}{int(number):05d}"
    return f"{PREFIXES[kind]}-{store['code']}-{document_date.year}{document_date.month:02d}-{int(number):05d}"

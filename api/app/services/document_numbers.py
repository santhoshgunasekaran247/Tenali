from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIXES = {"invoice": "INV", "purchase": "PUR"}


def next_document_number(db: Session, company_id: str, store: dict, kind: str, document_date: date) -> str:
    """Per-store, per-month running number: INV-<STORE>-YYYYMM-NNNNN or PUR-<STORE>-YYYYMM-NNNNN.

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
    return f"{PREFIXES[kind]}-{store['code']}-{document_date.year}{document_date.month:02d}-{int(number):05d}"

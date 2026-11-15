from datetime import date

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

PREFIXES = {"invoice": "INV", "purchase": "PUR"}
MAX_INVOICE_SEQUENCE = 999_999_999_999


def next_document_number(db: Session, company_id: str, store: dict, kind: str, document_date: date) -> str:
    """Issue a store-specific invoice series or a monthly purchase voucher number.

    Invoice counters use one lifetime sequence per store. That keeps each store's GST
    series consecutive across financial years, while the permanent store code keeps
    series distinct. Existing monthly counters and invoices seed the first new number.
    The upsert takes a row lock, so concurrent postings in one store serialize.
    """
    if kind == "invoice":
        number = db.execute(
            text(
                """
                insert into document_sequences (company_id, store_id, kind, year, month, last_number)
                values (
                    :company, :store, :kind, 0, 1,
                    greatest(
                        coalesce((
                            select sum(last_number) from document_sequences
                            where company_id = :company and store_id = :store and kind = :kind
                        ), 0),
                        coalesce((
                            select count(*) from invoices
                            where company_id = :company and store_id = :store
                        ), 0),
                        coalesce((
                            select max(substring(invoice_number from length(:series_prefix) + 1)::bigint)
                            from invoices
                            where company_id = :company and store_id = :store
                                and invoice_number like :series_prefix || '%'
                                and char_length(invoice_number) = 16
                                and substring(invoice_number from length(:series_prefix) + 1) ~ '^[0-9]{12}$'
                        ), 0)
                    ) + 1
                )
                on conflict (company_id, store_id, kind, year, month)
                do update set last_number = document_sequences.last_number + 1
                returning last_number
                """
            ),
            {
                "company": company_id,
                "store": str(store["id"]),
                "kind": kind,
                "series_prefix": f"I{store['invoice_code']}-",
            },
        ).scalar_one()
        if int(number) > MAX_INVOICE_SEQUENCE:
            raise HTTPException(422, "This store has reached the invoice sequence limit; a 16-character invoice number cannot be generated.")
        return f"I{store['invoice_code']}-{int(number):012d}"

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

"""Bounded, selected-field Operations reads; no raw audit payloads or full exports."""
from datetime import date

from sqlalchemy import text

from app.services.access import allowed_stores
from app.services.accounts_service import AccountsService
from app.services.borrowing_ledger import ACTIVE_BORROWING


def lookup(db, identity, key, args):
    params = {"company": str(identity["company_id"]), "query": args.query, "limit": args.limit + 1,
              "from_date": args.from_date, "to_date": args.to_date, "as_of": args.as_of or date.today(),
              "store": str(args.store_id) if args.store_id else None, "permitted": allowed_stores(identity)}
    dates = """ and (cast(:from_date as date) is null or {column}::date>=cast(:from_date as date))
        and (cast(:to_date as date) is null or {column}::date<=cast(:to_date as date))"""
    store_scope = """ and (cast(:store as uuid) is null or {column}=cast(:store as uuid))
        and (cast(:permitted as uuid[]) is null or {column}=any(cast(:permitted as uuid[])))"""
    if key == "account_journal":
        result = AccountsService(db).list_audit_journal(params["company"], "daily",
            args.from_date.isoformat() if args.from_date else None, args.to_date.isoformat() if args.to_date else None,
            limit=args.limit + 1)
        # This service has no search argument; query filtering must precede LIMIT.
        if args.query:
            from fastapi import HTTPException
            raise HTTPException(422, "Account journal accepts date filters only; use transactions for text search.")
        return {"items": result["items"], "note": "Bounded journal entries only, no complete totals. Use private account-journal export for the complete selected window."}
    if key in {"product_details", "variants", "vendor_offers"}:
        source = {"product_details": "products p", "variants": "product_variants r join products p on p.id=r.product_id",
                  "vendor_offers": "vendor_contributions r join products p on p.id=r.product_id join parties v on v.id=r.vendor_id and v.company_id=p.company_id"}[key]
        alias = "p" if key == "product_details" else "r"
        labels = "p.name" + (",r.variant_name,coalesce(r.sku,'')" if key == "variants" else ",v.legal_name" if key == "vendor_offers" else ",coalesce(p.sku,'')")
        query = f"""select {alias}.*,p.name as product_name from {source} where p.company_id=:company
            and (:query='' or {alias}.id::text=:query or p.id::text=:query
                or strpos(lower(concat_ws(' ',{labels})),lower(:query))>0)
            order by p.name,{alias}.id limit :limit"""
        note = "Product/variant/offer metadata only; no owned-stock totals, credentials or vendor contact details. Query can be an exact verified UUID or product/variant/vendor label."
    elif key == "borrowing_entries":
        query = f"""select b.id,b.party_id,p.legal_name as party_name,b.direction,b.amount,b.transaction_date,
            b.account_id,b.source_transaction_id from borrowings b join parties p on p.id=b.party_id and p.company_id=b.company_id
            where b.company_id=:company and {ACTIVE_BORROWING}
            and (:query='' or b.id::text=:query or strpos(lower(p.legal_name),lower(:query))>0)""" + dates.format(column="b.transaction_date") + """
            order by b.transaction_date desc,b.id limit :limit"""
        note = "Individual active borrowing/repayment entries, excluding reversals. Date filters use transaction date; no company-wide totals."
    elif key == "stock_transfers":
        query = """select t.id,t.from_store_id,t.to_store_id,src.code as from_store_code,dst.code as to_store_code,
            t.transfer_date,t.reference,t.reversal_of_transfer_id,
            (select r.id from stock_transfers r where r.company_id=t.company_id and r.reversal_of_transfer_id=t.id) as reversed_by_transfer_id
            from stock_transfers t join stores src on src.id=t.from_store_id and src.company_id=t.company_id
            join stores dst on dst.id=t.to_store_id and dst.company_id=t.company_id where t.company_id=:company
            and (:query='' or t.id::text=:query or strpos(lower(concat_ws(' ',src.code,dst.code,t.reference)),lower(:query))>0)
            and (cast(:store as uuid) is null or t.from_store_id=cast(:store as uuid) or t.to_store_id=cast(:store as uuid))
            and (cast(:permitted as uuid[]) is null or
                 (t.from_store_id=any(cast(:permitted as uuid[])) and t.to_store_id=any(cast(:permitted as uuid[]))))""" + dates.format(column="t.transfer_date") + """
            order by t.transfer_date desc,t.id limit :limit"""
        note = "Only transfers whose source and destination stores are both permitted. Includes reversal references, not all transfer lines."
    elif key in {"stock_movements", "movement_sources"}:
        query = """select m.id,m.store_id,s.code as store_code,m.product_id,p.name as product_name,m.variant_id,
            v.variant_name,m.movement_type,m.quantity,m.reference_type,m.reference_id,m.created_at
            from stock_movements m join products p on p.id=m.product_id and p.company_id=m.company_id
            join stores s on s.id=m.store_id and s.company_id=m.company_id
            left join product_variants v on v.id=m.variant_id where m.company_id=:company
            and (:query='' or m.id::text=:query or m.product_id::text=:query
                or strpos(lower(concat_ws(' ',p.name,v.variant_name,p.sku)),lower(:query))>0)"""
        if key == "movement_sources":
            query += """ and ((m.reference_type in ('invoice','invoice_cancellation') and not exists(
                select 1 from invoices i where i.company_id=m.company_id and i.id=m.reference_id))
                or (m.reference_type in ('purchase_receipt','purchase_cancellation') and not exists(
                select 1 from purchases pu where pu.company_id=m.company_id and pu.id=m.reference_id)))"""
        query += store_scope.format(column="m.store_id") + dates.format(column="m.created_at") + """
            order by m.created_at desc,m.id limit :limit"""
        note = "Per-permitted-store movement records; date filters use creation date. Missing-source attribution does not change quantities."
    elif key in {"collection_reminders", "reminder_history"}:
        if key == "collection_reminders":
            query = """select r.id,r.party_id,p.legal_name as party_name,r.invoice_id,r.status,
                r.amount_due,r.amount_received,r.due_date,r.reminder_date from receivables r
                join parties p on p.id=r.party_id and p.company_id=r.company_id
                left join invoices i on i.id=r.invoice_id and i.company_id=r.company_id where r.company_id=:company
                and r.status in ('UNPAID','PARTIAL') and coalesce(r.reminder_date,r.due_date)<=:as_of
                and (i.id is null or i.status<>'CANCELLED')
                and (:query='' or r.id::text=:query or strpos(lower(p.legal_name),lower(:query))>0)"""
            query += store_scope.format(column="i.store_id") + " order by coalesce(r.reminder_date,r.due_date),r.id limit :limit"
        else:
            query = """select h.id,h.receivable_id,p.legal_name as party_name,h.reminder_date,h.next_reminder_date,h.reminded_at
                from receivable_reminders h join receivables r on r.id=h.receivable_id and r.company_id=h.company_id
                join parties p on p.id=r.party_id and p.company_id=r.company_id
                left join invoices i on i.id=r.invoice_id and i.company_id=r.company_id where h.company_id=:company
                and (:query='' or r.id::text=:query or strpos(lower(p.legal_name),lower(:query))>0)"""
            query += store_scope.format(column="i.store_id") + dates.format(column="h.reminded_at") + " order by h.reminded_at desc,h.id limit :limit"
        note = "Reminder state/history for permitted invoice stores; standalone receivables require unrestricted stores. Reminder logging does not send customer messages."
    elif key == "audit_events":
        query = """select id,action,entity_type,entity_id,created_at from audit_events where company_id=:company
            and (:query='' or strpos(lower(concat_ws(' ',action,entity_type)),lower(:query))>0)"""
        query += dates.format(column="created_at") + " order by created_at desc,id limit :limit"
        note = "Audit event identifiers and actions only; excludes actors and all old/new private payloads. Not a full export."
    else:
        raise ValueError(f"No Operations read adapter for {key}")
    items = [dict(row) for row in db.execute(text(query), params).mappings()]
    if key == "product_details":
        for item in items:
            item["image_urls"] = [source for source in (item.get("image_urls") or "").split("|") if source]
    return {"items": items, "note": note}

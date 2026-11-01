from datetime import date

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.access import allowed_stores, is_super
from app.services.settlements_service import SettlementsService
from app.services.stores_service import get_store


class DashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.identity = db.info["tenant_context"]

    def summary(self, month: date | None = None, store_id: str | None = None) -> dict:
        start = month or date.today().replace(day=1)
        if start.day != 1 or start.year == 9999:
            raise HTTPException(422, "Choose the first day of a supported month")
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        company = str(self.identity["company_id"])
        stores = allowed_stores(self.identity)
        if store_id:
            get_store(self.db, company, store_id, require_active=False)
            stores = [store_id]
        params = {"company": company, "stores": stores, "start": start, "end": end, "today": date.today()}
        scope = "company_id=:company and (cast(:stores as uuid[]) is null or store_id=any(cast(:stores as uuid[])))"

        def permitted(module):
            return is_super(self.identity) or self.identity.get("modules") is None or module in self.identity["modules"]

        def one(query):
            return dict(self.db.execute(text(query), params).mappings().one())

        result = {"month": start, "store_id": store_id, "inventory": None, "orders": None, "purchases": None,
                  "sales": None, "receivables": None, "borrowing_outstanding": None}
        if permitted("inventory"):
            result["inventory"] = one(f"""
                with quantities as (
                    select product_id,variant_id,sum(quantity) quantity from stock_balances
                    where {scope} group by product_id,variant_id
                ), items as (
                    select p.id,p.is_active,p.reorder_enabled,p.reorder_level,
                        coalesce((select sum(q.quantity) from quantities q where q.product_id=p.id),0) quantity
                    from products p where p.company_id=:company
                    union all
                    select v.id,p.is_active and v.is_active,v.reorder_enabled,v.reorder_level,coalesce(q.quantity,0)
                    from product_variants v join products p on p.id=v.product_id
                    left join quantities q on q.product_id=p.id and q.variant_id=v.id
                    where p.company_id=:company
                )
                select (select count(*) from products where company_id=:company) total_products,
                    (select count(*) from products where company_id=:company and is_active) active_products,
                    (select count(*) from product_categories where company_id=:company and is_active) categories,
                    (select coalesce(sum(quantity),0) from quantities) quantity_in_hand,
                    count(*) filter(where is_active and reorder_enabled and quantity<=reorder_level
                        and (cast(:stores as uuid[]) is null or cardinality(cast(:stores as uuid[]))>0)) low_stock_items
                from items
            """)
        if permitted("orders") and is_super(self.identity):
            activity = one(f"""
                select count(*) filter(where status='cod_requested') to_confirm,
                    count(*) filter(where fulfilment_method='delivery' and status in
                        ('paid','confirmed','shipping_pending','shipment_booked')) to_ship,
                    count(*) filter(where status='dispatched') to_deliver,
                    count(*) filter(where status='ready_for_pickup') to_collect,
                    count(*) filter(where status='fulfilment_review') needs_review,
                    count(*) filter(where invoice_id is null and status in
                        ('paid','confirmed','shipping_pending','shipment_booked','dispatched','delivered','ready_for_pickup','collected')) to_invoice
                from shop_orders where {scope}
                    and (expires_at is null or expires_at>now() or status not in ('awaiting_payment','cod_requested','confirmed'))
            """)
            channels = self.db.execute(text(f"""
                select channel,count(*) total,
                    count(*) filter(where status='awaiting_payment' and (expires_at is null or expires_at>now())) awaiting_payment,
                    count(*) filter(where status in ('paid','confirmed','cod_requested')
                        and (status='paid' or expires_at is null or expires_at>now())) confirmed,
                    count(*) filter(where status in ('shipping_pending','shipment_booked')) to_ship,
                    count(*) filter(where status='dispatched') dispatched,
                    count(*) filter(where status in ('delivered','collected')) completed,
                    count(*) filter(where status in ('cancelled','refunded','expired')
                        or (expires_at<=now() and status in ('awaiting_payment','cod_requested','confirmed'))) closed,
                    count(*) filter(where status='fulfilment_review') needs_review,
                    count(*) filter(where status='ready_for_pickup') ready_for_pickup
                from shop_orders where {scope} and created_at>=:start and created_at<:end
                group by channel order by channel
            """), params).mappings().all()
            result["orders"] = {**activity, "channels": [dict(row) for row in channels]}
        if permitted("purchases"):
            result["purchases"] = one(f"""
                select count(*) filter(where purchase_date>=:start and purchase_date<:end) bills,
                    coalesce(sum(total) filter(where purchase_date>=:start and purchase_date<:end),0) total,
                    count(*) filter(where receipt_status='PENDING' and receipt_type<>'SERVICE') pending_receipts,
                    coalesce(sum((select coalesce(sum((line->>'quantity')::numeric),0)
                        from jsonb_array_elements(line_items) line))
                        filter(where receipt_status='PENDING' and receipt_type<>'SERVICE'),0) quantity_to_receive
                from purchases where {scope} and status='POSTED'
            """)
        if permitted("billing"):
            sales = one(f"""
                select count(*) invoices,coalesce(sum(total),0) total
                from invoices where {scope} and status='POSTED' and invoice_date>=:start and invoice_date<:end
            """)
            top = self.db.execute(text(f"""
                select line->>'product_id' product_id,
                    coalesce(p.name,line->>'description') name,p.image_url,
                    coalesce(p.uom,'units') uom,sum((line->>'quantity')::numeric) quantity
                from invoices i cross join lateral jsonb_array_elements(i.document_data->'lines') line
                left join products p on p.id::text=line->>'product_id' and p.company_id=i.company_id
                where i.company_id=:company
                    and (cast(:stores as uuid[]) is null or i.store_id=any(cast(:stores as uuid[])))
                    and i.status='POSTED' and i.invoice_date>=:start and i.invoice_date<:end
                    and nullif(line->>'product_id','') is not null
                group by line->>'product_id',coalesce(p.name,line->>'description'),p.image_url,p.uom
                order by quantity desc,name,product_id limit 5
            """), params).mappings().all()
            result["sales"] = {**sales, "top_items": [dict(row) for row in top]}
        if permitted("receivables"):
            result["receivables"] = one(f"""
                select count(*) filter(where status in ('UNPAID','PARTIAL')) open,
                    count(*) filter(where status='BAD_DEBT') bad_debt,
                    count(*) filter(where status in ('UNPAID','PARTIAL') and coalesce(reminder_date,due_date)<=:today) reminders_due
                from receivables where {scope}
            """)
        if permitted("settlements") and stores is None:
            result["borrowing_outstanding"] = sum(row["net_outstanding"] for row in
                SettlementsService(self.db).summarize_borrowings(company)["items"])
        return result

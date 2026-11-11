"""Explicit private report downloads, separate from provider context and outcome history."""
import csv
import hashlib
from datetime import date
from io import StringIO
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from app.services.access import allowed_stores, check_module
from app.services.accounts_service import AccountsService
from app.services.billing_service import BillingService
from app.services.collections_service import CollectionsService
from app.services.purchases_service import PurchasesService
from app.services.gst_reconciliation import reconcile_2b

REPORT_MODULES = {
    "account_transactions": "/accounts", "account_journal": "/accounts", "sales_register": "/billing",
    "purchase_register": "/purchases", "ar_aging": "/collections", "ap_aging": "/purchases",
    "gst_reconcile": "/purchases",
}
MAX_REPORT_ROWS = 5000
MAX_REPORT_BYTES = 5_000_000


def gate(identity, kind):
    check_module(identity, "/reports")
    check_module(identity, REPORT_MODULES[kind])
    if allowed_stores(identity) is not None:
        raise HTTPException(403, "These company-wide reports require unrestricted store access.")


def generate(db, company, action, values):
    kind = values["kind"] if action == "report_export" else "gst_reconcile"
    gate(db.info["tenant_context"], kind)
    start, end, as_of = values.get("from_date"), values.get("to_date"), values.get("as_of")
    aging = kind in {"ar_aging", "ap_aging"}
    if aging:
        if not as_of or start or end:
            raise HTTPException(422, "Aging needs an explicit as_of date and no date range.")
    elif not start or not end or start > end or as_of:
        raise HTTPException(422, "Choose a valid explicit date range, without an as_of date.")
    if kind != "account_journal" and values.get("period", "daily") != "daily":
        raise HTTPException(422, "Only account journal reports accept a grouping period.")
    table, date_field = (
        ("account_transactions", "transaction_date") if kind.startswith("account_") else
        ("invoices", "invoice_date") if kind == "sales_register" else
        ("receivables", None) if kind == "ar_aging" else ("purchases", None if aging else "purchase_date")
    )
    count = db.execute(text(f"select count(*) from {table} where company_id=:company" +
        (f" and {date_field} between cast(:start as date) and cast(:end as date)" if date_field else "")),
        {"company": company, "start": start, "end": end}).scalar_one()
    if count > MAX_REPORT_ROWS:
        raise HTTPException(422, "AI downloads support at most 5,000 source records. Narrow the date range or use Reports & Exports for larger reports.")
    if kind == "account_transactions":
        content = AccountsService(db).export_transactions_csv(company, limit=MAX_REPORT_ROWS, from_date=start, to_date=end)
    elif kind == "account_journal":
        content = AccountsService(db).export_journal_csv(company, values["period"], start, end, limit=MAX_REPORT_ROWS)
    elif kind == "sales_register":
        content = BillingService(db).export_sales_register_csv(company, start, end)
    elif kind == "purchase_register":
        content = PurchasesService(db).export_purchase_register_csv(company, start, end)
    elif kind == "ar_aging":
        content = CollectionsService(db).export_ar_aging_csv(company, as_of)
    elif kind == "ap_aging":
        content = PurchasesService(db).export_ap_aging_csv(company, as_of)
    else:
        reconciliation = reconcile_2b(db, company, values["csv_text"], date.fromisoformat(start), date.fromisoformat(end))
        output = StringIO()
        fields = ("supplier_gstin", "invoice_number", "status", "books_taxable", "statement_taxable", "books_gst", "statement_gst", "gst_difference")
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(reconciliation["items"])
        content = output.getvalue()
    raw = content.encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        raise HTTPException(422, "The private report exceeds 5 MB. Narrow the period or use Reports & Exports.")
    preview = {"kind": kind, "from_date": start, "to_date": end, "as_of": as_of,
               "source_records": count, "rows": max(0, sum(1 for _ in csv.reader(StringIO(content))) - 1),
               "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
               "download_expires": "One hour, or earlier when the conversation expires/is deleted.",
               "provider_receives_export": False}
    if kind == "gst_reconcile":
        preview.update(counts=reconciliation["counts"], working_paper_only=True, limitations=reconciliation["limitations"])
    return raw, preview


def apply(db, company, action, values, key, approved):
    raw, current = generate(db, company, action, values)
    if current != approved:
        raise HTTPException(409, "Report data changed. Review and approve a fresh report.")
    execution_id = UUID(key.removeprefix("ai-"))
    user = db.info["tenant_context"]["user_id"]
    db.execute(text("""insert into ai_report_files(id,company_id,user_id,kind,file_name,content,expires_at)
        values(:id,:company,:user,:kind,:name,:content,now()+interval '1 hour')"""),
        {"id": execution_id, "company": company, "user": user, "kind": current["kind"],
         "name": f"tenali-{current['kind']}.csv", "content": raw})
    return {"report_id": str(execution_id), "report_rows": current["rows"]}


def download(assistant, execution_id):
    from app.ai.execution import ExecutionService
    from app.ai.drafts import DraftService
    execution = ExecutionService(assistant).get(execution_id)
    if execution["status"] != "succeeded" or "report_id" not in execution["result"]:
        raise HTTPException(404, "Private report not found.")
    draft = DraftService(assistant).get(execution["draft_id"])
    identity, _ = DraftService(assistant).gate(draft["action_key"])
    row = assistant.db.execute(text("""select kind,file_name,content from ai_report_files
        where id=:id and company_id=:company and user_id=:user and expires_at>now() and content is not null"""),
        {**assistant.scope, "id": str(execution_id)}).mappings().first()
    if not row:
        raise HTTPException(410, "This private download has expired or was removed. Prepare a new report.")
    gate(identity, row["kind"])
    return Response(bytes(row["content"]), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{row["file_name"]}"',
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy

from fastapi import HTTPException

from app.schemas.billing import InvoiceCreate
from app.schemas.company import InvoiceSettings


def build_invoice_document(payload: InvoiceCreate, company: dict, customer: dict) -> dict:
    billing_address = (payload.billing_address or customer.get("address") or "").strip()
    supply = payload.place_of_supply or ""
    seller_gst = str(company.get("gst_number") or "").strip()
    if not billing_address or not supply or not company.get("address") or len(seller_gst) != 15:
        raise HTTPException(
            status_code=422,
            detail="Itemized tax invoices require company address/GSTIN, billing address and place of supply",
        )
    interstate = seller_gst[:2] != supply[:2]
    quantum = Decimal("0.01")
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    lines = []
    for line in payload.lines:
        taxable = (line.quantity * line.rate).quantize(quantum, rounding=ROUND_HALF_UP)
        tax = (taxable * line.gst_rate / 100).quantize(quantum, rounding=ROUND_HALF_UP)
        cgst = Decimal("0") if interstate else (tax / 2).quantize(quantum, rounding=ROUND_HALF_UP)
        sgst = Decimal("0") if interstate else tax - cgst
        lines.append({
            **line.model_dump(mode="json"),
            "taxable": str(taxable),
            "cgst": str(cgst),
            "sgst": str(sgst),
            "igst": str(tax if interstate else Decimal("0")),
            "total": str(taxable + tax),
        })
        subtotal += taxable
        tax_total += tax
    seller = deepcopy(company)
    seller["invoice_settings"] = InvoiceSettings.model_validate(company.get("invoice_settings") or {}).model_dump()
    return {
        "seller": seller,
        "bill_to": {"name": customer["legal_name"], "address": billing_address, "gst_number": customer.get("gst_number")},
        "ship_to": {"name": payload.shipping_name or customer["legal_name"], "address": payload.shipping_address or billing_address},
        "place_of_supply": supply,
        "interstate": interstate,
        "lines": lines,
        "subtotal": str(subtotal),
        "gst_total": str(tax_total),
        "total": str(subtotal + tax_total),
    }
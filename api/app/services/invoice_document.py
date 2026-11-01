from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
import re

from fastapi import HTTPException

from app.schemas.billing import InvoiceCreate
from app.schemas.company import GSTIN_PATTERN, InvoiceSettings
from app.services.financial_amounts import line_amounts


def build_invoice_document(payload: InvoiceCreate, company: dict, customer: dict, store: dict | None = None,
                           prices_include_gst: bool = True) -> dict:
    billing_address = (payload.billing_address or customer.get("address") or "").strip()
    supply = payload.place_of_supply or ""
    registered = company.get("gst_registered", True) is not False
    seller_gst = str((store or {}).get("gst_number") or company.get("gst_number") or "").strip()
    seller_address = (store or {}).get("address") or company.get("address")
    if not registered:
        # Below the GST threshold: a Bill of Supply carries no tax and needs no GSTIN.
        for line in payload.lines:
            line.gst_rate = Decimal("0")
        if not seller_address:
            raise HTTPException(status_code=422, detail="Itemized bills require a company address in Company Setup")
    elif not seller_address or not re.fullmatch(GSTIN_PATTERN, seller_gst):
        raise HTTPException(
            status_code=422,
            detail="Itemized tax invoices require a company address and valid 15-character GSTIN in Company Setup",
        )
    if not billing_address or not supply:
        raise HTTPException(
            status_code=422,
            detail="Itemized tax invoices require a billing address and place of supply",
        )
    seller_state = (store or {}).get("state_code") or seller_gst[:2]
    interstate = bool(seller_state) and seller_state != supply[:2]
    quantum = Decimal("0.01")
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    lines = []
    for line in payload.lines:
        inclusive = prices_include_gst if line.price_includes_gst is None else line.price_includes_gst
        taxable, tax = line_amounts(line.quantity, line.rate, line.gst_rate, inclusive)
        cgst = Decimal("0") if interstate else (tax / 2).quantize(quantum, rounding=ROUND_HALF_UP)
        sgst = Decimal("0") if interstate else tax - cgst
        lines.append({
            **line.model_dump(mode="json"),
            "price_includes_gst": inclusive,
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
    seller["gst_number"] = seller_gst
    seller["address"] = seller_address
    if store:
        seller["store"] = {"code": store.get("code"), "name": store.get("name")}
    return {
        "seller": seller,
        "bill_to": {"name": customer["legal_name"], "address": billing_address, "gst_number": customer.get("gst_number")},
        "ship_to": {"name": payload.shipping_name or customer["legal_name"], "address": payload.shipping_address or billing_address},
        "place_of_supply": supply,
        "interstate": interstate,
        "pricing": "inclusive" if prices_include_gst else "exclusive",
        "document_title": "TAX INVOICE" if registered else "BILL OF SUPPLY",
        "gst_registered": registered,
        "lines": lines,
        "subtotal": str(subtotal),
        "gst_total": str(tax_total),
        "total": str(subtotal + tax_total),
    }
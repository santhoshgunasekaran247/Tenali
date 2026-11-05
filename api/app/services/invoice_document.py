from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.schemas.billing import InvoiceCreate
from app.schemas.company import InvoiceSettings
from app.services.financial_amounts import line_amounts


def build_invoice_document(
    payload: InvoiceCreate,
    company: dict,
    customer: dict,
    store: dict | None = None,
    prices_include_gst: bool = True,
) -> dict:
    billing_address = (payload.billing_address or customer.get("address") or "").strip()
    supply = payload.place_of_supply or ""
    gst_registered = company.get("gst_registered", True)
    seller_gst = str((store or {}).get("gst_number") or company.get("gst_number") or "").strip() if gst_registered else ""
    seller_address = (store or {}).get("address") or company.get("address")
    if not billing_address or not supply or not seller_address or (gst_registered and len(seller_gst) != 15):
        raise HTTPException(
            status_code=422,
            detail="Itemized invoices require a seller address, billing address and place of supply; GST-registered sellers also require a GSTIN",
        )
    seller_state = (store or {}).get("state_code") or seller_gst[:2]
    interstate = bool(seller_state and seller_state != supply[:2])
    quantum = Decimal("0.01")
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    lines = []
    for line in payload.lines:
        inclusive = prices_include_gst if line.price_includes_gst is None else line.price_includes_gst
        gst_rate = line.gst_rate if gst_registered else Decimal("0")
        taxable, tax = line_amounts(line.quantity, line.rate, gst_rate, inclusive)
        cgst = Decimal("0") if interstate else (tax / 2).quantize(quantum, rounding=ROUND_HALF_UP)
        sgst = Decimal("0") if interstate else tax - cgst
        lines.append({
            **line.model_dump(mode="json"),
            "gst_rate": str(gst_rate),
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
    seller["address"] = seller_address
    seller["gst_number"] = seller_gst or None
    if store is not None:
        seller["store"] = jsonable_encoder(store)
    seller["invoice_settings"] = InvoiceSettings.model_validate(company.get("invoice_settings") or {}).model_dump()
    return {
        "document_title": "TAX INVOICE" if gst_registered else "BILL OF SUPPLY",
        "gst_registered": gst_registered,
        "pricing": "inclusive" if prices_include_gst else "exclusive",
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
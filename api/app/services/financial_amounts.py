from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

MAX_MONEY = Decimal("999999999999.99")
PAISE = Decimal("0.01")


def document_total(subtotal: Decimal, gst_total: Decimal, supplied_total: Decimal | None) -> Decimal:
    total = subtotal + gst_total
    if total > MAX_MONEY:
        raise HTTPException(422, "Document total exceeds the supported monetary limit")
    if supplied_total is not None and supplied_total != total:
        raise HTTPException(422, "total must equal subtotal plus gst_total")
    if total <= 0:
        raise HTTPException(422, "total must be greater than zero")
    return total


def line_amounts(quantity: Decimal, rate: Decimal, gst_rate: Decimal, inclusive: bool) -> tuple[Decimal, Decimal]:
    """Return (taxable, gst) in paise for one line.

    Exclusive: taxable = qty x rate, GST on top. Inclusive: qty x rate is the amount charged; the
    taxable value is backed out so that taxable + GST equals that amount exactly. Both use half-up
    rounding, matching web/src/features/taxTotals.ts.
    """
    gross = (quantity * rate).quantize(PAISE, rounding=ROUND_HALF_UP)
    if inclusive:
        taxable = (gross / (1 + gst_rate / 100)).quantize(PAISE, rounding=ROUND_HALF_UP)
        return taxable, gross - taxable
    return gross, (gross * gst_rate / 100).quantize(PAISE, rounding=ROUND_HALF_UP)

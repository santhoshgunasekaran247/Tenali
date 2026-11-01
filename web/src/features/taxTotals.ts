import type { InvoiceLineInput } from "../types";

const MAX_TOTAL_PAISE = 99999999999999n;

function scaledInteger(value: number, scale: number): bigint | null {
  const scaled = Math.round(value * scale);
  return value >= 0 && Number.isSafeInteger(scaled) ? BigInt(scaled) : null;
}

/** Half-up division of non-negative bigints. */
function divideHalfUp(numerator: bigint, denominator: bigint): bigint {
  return (numerator * 2n + denominator) / (denominator * 2n);
}

/**
 * Per-line paise arithmetic matching api/app/services/financial_amounts.line_amounts.
 * Exclusive lines: taxable = qty x rate, GST on top. Inclusive lines (the default for sales):
 * qty x rate is the amount charged and the taxable value is backed out so taxable + GST equals it exactly.
 */
export function calculateLineTotals(lines: InvoiceLineInput[], pricesIncludeGst = false) {
  let subtotalPaise = 0n;
  let gstPaise = 0n;
  for (const line of lines) {
    const quantity = scaledInteger(line.quantity, 1000);
    const rate = scaledInteger(line.rate, 100);
    const gstRate = scaledInteger(line.gst_rate, 100);
    if (quantity === null || rate === null || gstRate === null) {
      return { subtotal: NaN, gstTotal: NaN, total: NaN };
    }
    const gross = (quantity * rate + 500n) / 1000n;
    const inclusive = line.price_includes_gst ?? pricesIncludeGst;
    let taxable: bigint;
    let gst: bigint;
    if (inclusive) {
      taxable = divideHalfUp(gross * 10000n, 10000n + gstRate);
      gst = gross - taxable;
    } else {
      taxable = gross;
      gst = (taxable * gstRate + 5000n) / 10000n;
    }
    subtotalPaise += taxable;
    gstPaise += gst;
  }
  const totalPaise = subtotalPaise + gstPaise;
  if (totalPaise > MAX_TOTAL_PAISE) {
    return { subtotal: NaN, gstTotal: NaN, total: NaN };
  }
  return {
    subtotal: Number(subtotalPaise) / 100,
    gstTotal: Number(gstPaise) / 100,
    total: Number(totalPaise) / 100,
  };
}

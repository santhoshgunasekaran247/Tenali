import { tenantFetch } from "./tenantTransport";
import type { InvoiceListResponse, Quotation } from "../types";

type Filters = Record<string, string | number | boolean | null | undefined>;

function query(filters: Filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return params.size ? `?${params}` : "";
}

async function get<T>(path: string, filters: Filters = {}): Promise<T> {
  const response = await tenantFetch(`/api${path}${query(filters)}`);
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try { message = JSON.parse(body).detail || body; } catch { /* retain response text */ }
    throw new Error(typeof message === "string" ? message : `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export type AuditEvent = { id: string; action: string; entity_type: string; entity_id: string; created_at: string; old_value: unknown; new_value: unknown };

export const historyClient = {
  audit: (filters: Filters) => get<{items: AuditEvent[]; next_cursor: string | null}>("/reports/audit-events", filters),
  invoices: (filters: Filters) => get<InvoiceListResponse>("/billing/invoices", filters),
  quotations: (filters: Filters) => get<{items: Quotation[]; next_cursor?: string | null}>("/billing/quotations", filters),
  async salesRegisterCsv(filters: Filters) {
    const response = await tenantFetch(`/api/billing/invoices/reports/sales-register/export${query(filters)}`);
    if (!response.ok) throw new Error((await response.text()) || `Request failed: ${response.status}`);
    return response.blob();
  },
  async reconcileCsv() {
    const response = await tenantFetch("/api/billing/invoices/reconcile-runs/export");
    if (!response.ok) throw new Error((await response.text()) || `Request failed: ${response.status}`);
    return response.blob();
  },
};

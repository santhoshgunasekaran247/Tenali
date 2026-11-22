import { API_BASE } from "../api";
import { tenantFetch } from "./tenantTransport";
import type { Receivable, ReceivableReminderLog } from "../types";

type Page<T> = { items: T[]; next_cursor?: string | null };
type Paging = { page_size?: number; cursor?: string | null; store_id?: string };
type Dates = { from_date?: string; to_date?: string };

async function get<T>(path: string, filters: object): Promise<Page<T>> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const response = await tenantFetch(`${API_BASE}/collections${path}?${params}`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        message = parsed.detail.map((item: { loc?: unknown[]; msg?: string }) =>
          `${item.loc?.join(".") || ""}: ${item.msg || "Invalid value"}`).join("; ");
      }
    } catch { /* A plain-text error is already readable. */ }
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json();
}

export const receivablesClient = {
  ledger: (filters: Paging & Dates & { status?: string; open_only?: boolean; search?: string; invoice_id?: string; receivable_id?: string } = {}) =>
    get<Receivable>("/receivables", filters),
  due: (filters: Paging & { as_of?: string } = {}) =>
    get<Receivable>("/receivables-reminders", filters),
  history: (id: string, filters: Paging & Dates & { reminded_by?: string } = {}) =>
    get<ReceivableReminderLog>(`/receivables/${encodeURIComponent(id)}/reminders`, filters),
};

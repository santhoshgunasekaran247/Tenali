import { accountRequest, type Shopper } from "./shop";
import type { Party } from "../types";

export type OnlineCustomer = Shopper & { customer_party_id: string | null };
type Page<T> = { items: T[]; next_cursor: string | null };

export function contactsPage(search: string, activeOnly: boolean, size: number, cursor: string | null) {
  const params = new URLSearchParams({ active_only: String(activeOnly), page_size: String(size) });
  if (search.trim()) params.set("search", search.trim());
  if (cursor) params.set("cursor", cursor);
  return accountRequest<Page<Party>>(`?${params}`, undefined, "parties");
}

export function onlineCustomersPage(search: string, size: number, cursor: string | null) {
  const params = new URLSearchParams({ page_size: String(size) });
  if (search.trim()) params.set("search", search.trim());
  if (cursor) params.set("cursor", cursor);
  return accountRequest<Page<OnlineCustomer>>(`/online-customers?${params}`, undefined, "parties");
}

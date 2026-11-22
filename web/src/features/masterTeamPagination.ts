import { useEffect, useState } from "react";
import { authRequest } from "./auth";
import { tenantFetch } from "./tenantTransport";

export type CursorPage<T> = { items: T[]; next_cursor: string | null };
export type MasterEntry = { id: string; name: string; code: string; description: string | null; is_active: boolean };
export type TeamMember = { id: string; email: string; display_name: string; role: string; is_active: boolean; store_ids: string[] | null; modules: string[] | null };

function query(size: number, cursor: string | null, search: string) {
  const params = new URLSearchParams({ page_size: String(size), search });
  if (cursor) params.set("cursor", cursor);
  return params.toString();
}

export async function masterPage(kind: string, size: number, cursor: string | null, search: string): Promise<CursorPage<MasterEntry>> {
  const response = await tenantFetch(`/api/inventory/lookups/${encodeURIComponent(kind)}?${query(size, cursor, search)}`);
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try { const parsed = JSON.parse(body); if (typeof parsed.detail === "string") detail = parsed.detail; } catch { /* use response text */ }
    throw new Error(detail || "Unable to load master entries.");
  }
  return response.json();
}

export function teamPage(_company: string, size: number, cursor: string | null, search: string): Promise<CursorPage<TeamMember>> {
  return authRequest(`/team?${query(size, cursor, search)}`);
}

export function useMasterTeamPage<T>(resource: string, loader: (resource: string, size: number, cursor: string | null, search: string) => Promise<CursorPage<T>>, enabled = true) {
  const [scope, setScope] = useState(resource);
  const [size, setSize] = useState(25);
  const [search, setSearchValue] = useState("");
  const [page, setPage] = useState(0);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [next, setNext] = useState<string | null>(null);
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const reset = () => { setPage(0); setCursors([null]); };

  useEffect(() => {
    if (scope !== resource) { setScope(resource); setSearchValue(""); reset(); }
  }, [scope, resource]);
  useEffect(() => {
    let active = true;
    if (!enabled || scope !== resource) { setItems([]); setNext(null); setLoading(false); return () => { active = false; }; }
    setLoading(true); setError(""); setItems([]); setNext(null);
    loader(resource, size, cursors[page], search).then(result => {
      if (active) { setItems(result.items); setNext(result.next_cursor); }
    }).catch(failure => {
      if (active) setError(failure instanceof Error ? failure.message : "Unable to load records.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [resource, scope, enabled, loader, size, cursors, page, search, revision]);

  return {
    items: enabled && scope === resource ? items : [], loading, error, size, page, next, search,
    setSearch: (value: string) => { reset(); setSearchValue(value); },
    setSize: (value: number) => { reset(); setSize(value); },
    previous: () => setPage(current => Math.max(0, current - 1)),
    advance: () => { if (next) { setCursors(current => [...current.slice(0, page + 1), next]); setPage(page + 1); } },
    refresh: () => { reset(); setRevision(current => current + 1); },
  };
}

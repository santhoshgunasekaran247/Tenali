import { useEffect, useState } from "react";
import { api } from "../api";
import type { Store } from "../types";

const KEY = "tenali.selectedStore";

/** Active stores for the workspace plus the staff member's remembered working store. */
export function useStores(includeInactive = false) {
  const [stores, setStores] = useState<Store[]>([]);
  const [error, setError] = useState("");
  const [selectedId, setSelectedIdState] = useState<string>(() => localStorage.getItem(KEY) || "");
  const reload = async () => {
    try {
      const result = await api.stores(includeInactive);
      setStores(result.items);
      setError("");
      return result.items;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to load stores.");
      return [];
    }
  };
  useEffect(() => { void reload(); }, [includeInactive]);
  useEffect(() => {
    if (!stores.length) return;
    const valid = stores.some(store => store.id === selectedId && store.is_active && store.holds_stock);
    if (!valid) {
      const fallback = stores.find(store => store.is_default) || stores.find(store => store.holds_stock && store.is_active);
      if (fallback) setSelectedId(fallback.id);
    }
  }, [stores]);
  const setSelectedId = (id: string) => { localStorage.setItem(KEY, id); setSelectedIdState(id); };
  const stockStores = stores.filter(store => store.holds_stock && store.is_active);
  const selected = stores.find(store => store.id === selectedId) || null;
  return { stores, stockStores, selected, selectedId, setSelectedId, reload, error };
}

export function StoreSelect({ value, onChange, stores, label = "Store", required = true, allowAll = false }:
  { value: string; onChange: (id: string) => void; stores: Store[]; label?: string; required?: boolean; allowAll?: boolean }) {
  return <label>{label}
    <select required={required} value={value} onChange={event => onChange(event.target.value)}>
      {allowAll ? <option value="">All stores</option> : null}
      {stores.map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}{store.is_default ? " (default)" : ""}</option>)}
    </select>
  </label>;
}

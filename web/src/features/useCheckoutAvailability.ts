import { useEffect, useState } from "react";
import { accountRequest, type Availability } from "./shop";
import { useAuth } from "./auth";
import { storefrontDisplay } from "./catalog/storefrontDisplay";
import { cartMode } from "./cartMode";

const CACHE_MS = 30_000;
const cache = new Map<string, { at: number; request: Promise<Availability> }>();

/** One shared /availability request per storefront for a short while, so the header, cards and pages do not each ask. */
function loadAvailability(companyId: string): Promise<Availability> {
  const cached = cache.get(companyId);
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.request;
  const request = accountRequest<Availability>("/availability");
  cache.set(companyId, { at: Date.now(), request });
  request.catch(() => cache.delete(companyId));
  return request;
}

export function useCheckoutAvailability(companyId?: string) {
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setAvailability(null); setError("");
    if (companyId) {
      loadAvailability(companyId)
        .then(result => { if (active) setAvailability(result); })
        .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : String(failure)); });
    }
    return () => { active = false; };
  }, [companyId]);
  return { availability, error };
}

/** Cart mode for the open storefront; `mode` is null until availability is known. */
export function useCartMode(enabled = true) {
  const { storefront } = useAuth();
  const { availability, error } = useCheckoutAvailability(enabled ? storefront?.id : undefined);
  const phone = storefrontDisplay(storefront).whatsapp_enquiry_enabled ? (storefront?.phone || "").replace(/\D/g, "") : "";
  const known = !!availability || !!error;
  return { mode: known ? cartMode(!!availability?.enabled, phone) : null, phone, availability, error };
}
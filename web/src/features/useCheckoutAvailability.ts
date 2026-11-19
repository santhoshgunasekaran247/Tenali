import { useEffect, useState } from "react";
import { accountRequest, type Availability } from "./shop";

export function useCheckoutAvailability(companyId?: string) {
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setAvailability(null); setError("");
    if (companyId) {
      accountRequest<Availability>("/availability")
        .then(result => { if (active) setAvailability(result); })
        .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : String(failure)); });
    }
    return () => { active = false; };
  }, [companyId]);
  return { availability, error };
}

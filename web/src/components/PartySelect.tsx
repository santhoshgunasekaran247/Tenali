import { useId, useState } from "react";
import type { Party } from "../types";

type Contact = Pick<Party, "id" | "legal_name" | "phone" | "email"> & { nickname?: string };

export function PartySelect({ parties, value, onChange, label = "Customer", required = false, disabled = false, placeholder }: {
  parties: Contact[]; value: string; onChange: (value: string) => void; label?: string;
  required?: boolean; disabled?: boolean; placeholder?: string;
}) {
  const [search, setSearch] = useState("");
  const id = useId();
  const query = search.trim().toLowerCase();
  const visible = parties.filter(party => party.id === value || !query ||
    [party.legal_name, party.nickname, party.email, party.phone].some(text => text?.toLowerCase().includes(query)) ||
    (!!party.phone && /^[+\d\s().-]+$/.test(query) && !!query.replace(/\D/g, "") && party.phone.replace(/\D/g, "").includes(query.replace(/\D/g, ""))));
  return <div className="party-selector">
    <label htmlFor={`${id}-search`}>Search {label.toLowerCase()} by name, email or phone
      <input id={`${id}-search`} type="search" value={search} disabled={disabled} autoComplete="off"
        onChange={event => setSearch(event.target.value)} placeholder="Name, email or phone" />
    </label>
    <label htmlFor={`${id}-select`}>{label}
      <select id={`${id}-select`} value={value} onChange={event => onChange(event.target.value)} required={required} disabled={disabled}>
        <option value="">{placeholder || `Select ${label.toLowerCase()}`}</option>
        {visible.map(party => <option key={party.id} value={party.id}>
          {[party.legal_name, party.email, party.phone].filter(Boolean).join(" · ")}
        </option>)}
      </select>
    </label>
    {!visible.length && query ? <p role="status">No matching {label.toLowerCase()}.</p> : null}
  </div>;
}

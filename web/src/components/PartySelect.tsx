import { useId, useState } from "react";
import type { Party } from "../types";

type Contact = Pick<Party, "id" | "legal_name" | "phone" | "email"> & { nickname?: string };

const MAX_RESULTS = 8;

export function matchParties<T extends Contact>(parties: T[], search: string): T[] {
  const query = search.trim().toLowerCase();
  if (!query) return parties;
  const digits = /^[+\d\s().-]+$/.test(query) ? query.replace(/\D/g, "") : "";
  return parties.filter(party =>
    [party.legal_name, party.nickname, party.email, party.phone].some(text => text?.toLowerCase().includes(query)) ||
    (!!digits && !!party.phone && party.phone.replace(/\D/g, "").includes(digits)));
}

const describe = (party: Contact) => [party.legal_name, party.email, party.phone].filter(Boolean).join(" · ");

export function PartySelect({ parties, value, onChange, label = "Customer", required = false, disabled = false, placeholder, emptyHint }: {
  parties: Contact[]; value: string; onChange: (value: string) => void; label?: string;
  required?: boolean; disabled?: boolean; placeholder?: string;
  /** Shown when nothing matches, e.g. why a party may be missing from the list. */
  emptyHint?: string;
}) {
  const [search, setSearch] = useState("");
  const id = useId();
  const query = search.trim();
  const matches = matchParties(parties, search);
  const visible = parties.filter(party => party.id === value || matches.includes(party));
  const choose = (party: Contact) => { onChange(party.id); setSearch(""); };
  return <div className="party-selector">
    <label htmlFor={`${id}-search`}>Search {label.toLowerCase()} by name, email or phone
      <input id={`${id}-search`} type="search" value={search} disabled={disabled} autoComplete="off"
        aria-controls={query ? `${id}-results` : undefined}
        onChange={event => setSearch(event.target.value)} placeholder="Name, email or phone"
        onKeyDown={event => { if (event.key === "Enter" && query && matches.length) { event.preventDefault(); choose(matches[0]); } }} />
    </label>
    {query ? <div id={`${id}-results`} className="party-results" role="group" aria-label={`Matching ${label.toLowerCase()}`}>
      {matches.slice(0, MAX_RESULTS).map(party => <button key={party.id} type="button" disabled={disabled}
        className={party.id === value ? "party-result is-selected" : "party-result"} aria-pressed={party.id === value}
        onClick={() => choose(party)}>{describe(party)}</button>)}
      {matches.length > MAX_RESULTS ? <small>{matches.length - MAX_RESULTS} more - keep typing to narrow the list.</small> : null}
      {!matches.length ? <p role="status">No matching {label.toLowerCase()}.{emptyHint ? ` ${emptyHint}` : ""}</p> : null}
    </div> : null}
    <label htmlFor={`${id}-select`}>{label}
      <select id={`${id}-select`} value={value} onChange={event => onChange(event.target.value)} required={required} disabled={disabled}>
        <option value="">{placeholder || `Select ${label.toLowerCase()}`}</option>
        {visible.map(party => <option key={party.id} value={party.id}>{describe(party)}</option>)}
      </select>
    </label>
    {!parties.length && emptyHint && !query ? <small className="party-hint">{emptyHint}</small> : null}
  </div>;
}

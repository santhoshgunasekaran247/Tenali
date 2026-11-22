import { CursorPagination } from "./CursorPagination";
import { FloatingAlert } from "./Notifications";
import { useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { onlineCustomersPage, type OnlineCustomer } from "../features/partiesPagination";
import { api } from "../api";
import { PartySelect } from "./PartySelect";
import type { Party } from "../types";

export function OnlineCustomerLinks() {
  const [items, setItems] = useState<OnlineCustomer[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<OnlineCustomer | null>(null);
  const [customer, setCustomer] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [partyError, setPartyError] = useState("");
  const [partyLoading, setPartyLoading] = useState(true);
  const [size, setSize] = useState(25);
  const [page, setPage] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [next, setNext] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [partyRevision, setPartyRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(""); setItems([]); setNext(null);
    onlineCustomersPage(search, size, cursors[page]).then(result => {
      if (active) { setItems(result.items); setNext(result.next_cursor); }
    }).catch(failure => { if (active) setLoadError(String(failure)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [search, size, page, cursors, revision]);
  useEffect(() => {
    let active = true;
    setPartyError(""); setPartyLoading(true);
    api.billingCustomers().then(result => { if (active) setParties(result.items); })
      .catch(failure => { if (active) setPartyError(String(failure)); })
      .finally(() => { if (active) setPartyLoading(false); });
    return () => { active = false; };
  }, [partyRevision]);
  const resetPage = () => { setPage(0); setCursors([null]); };
  const refresh = () => setRevision(value => value + 1);
  const link = async () => {
    if (!selected || !customer || !confirmed) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await accountRequest(`/online-customers/${selected.id}/link`, { method: "POST", body: JSON.stringify({ customer_party_id: customer }) }, "parties");
      setSelected(null); setMessage("Linked for future invoices. Past invoices and shopper orders are unchanged.");
      refresh();
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="ops-card"><h2>Online customer accounts</h2>
    <p>Online customers are separate from counter customers. Phone numbers are unverified. Only link after confirming the customer's identity directly.</p>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {loadError ? <><FloatingAlert>{loadError}</FloatingAlert><button className="ops-link-btn" type="button" disabled={loading} onClick={refresh}>Retry</button></> : null}
    {partyError ? <><FloatingAlert>{partyError}</FloatingAlert><button className="ops-link-btn" type="button" onClick={() => setPartyRevision(value => value + 1)}>Retry counter customers</button></> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <label className="online-customer-search">Search online customers<input type="search" value={search} onChange={event => { setSearch(event.target.value); resetPage(); }} placeholder="Name, email or phone" /></label>
    <button type="button" onClick={() => { setSearch(""); resetPage(); }}>Reset filters</button>
    {loading ? <p role="status">Loading online customer accounts...</p> : null}
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Name</th><th>Email</th><th>Phone (unverified)</th><th>Counter link</th></tr></thead>
      <tbody>{items.map(item =>
        <tr key={item.id}><td>{item.display_name}</td><td>{item.email}</td><td>{item.phone}</td><td>{item.customer_party_id ? "Linked" :
          <button className="ops-link-btn" type="button" disabled={busy||loading||partyLoading||!!partyError} onClick={() => { setSelected(item); setCustomer(""); setConfirmed(false); setError(""); }}>Link manually</button>}</td></tr>)}
        {!loading&&!loadError&&!items.length?<tr><td colSpan={4}>{search.trim()?"No matching online customers.":"No online customer accounts yet."}</td></tr>:null}</tbody>
    </table></div>
    <CursorPagination size={size} page={page} hasNext={!!next} busy={loading} onSize={value => { setSize(value); resetPage(); }}
      onPrevious={() => setPage(value => value - 1)} onNext={() => { if (next) { setCursors(values => [...values.slice(0, page + 1), next]); setPage(value => value + 1); } }} />
    {selected ? <fieldset disabled={busy}><legend>Link {selected.display_name} ({selected.email})</legend>
      <PartySelect parties={parties} value={customer} onChange={setCustomer} label="Counter customer" />
      <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I have confirmed this shopper and counter customer are the same person; a matching phone alone is not proof.</label>
      <button className="btn light" type="button" disabled={!customer || !confirmed || busy} onClick={() => void link()}>Confirm link</button>
      <button className="ops-link-btn" type="button" onClick={() => setSelected(null)}>Cancel</button>
    </fieldset> : null}
  </section>;
}

import { useEffect, useState } from "react";
import { accountRequest, type Shopper } from "../features/shop";
import { api } from "../api";
import { PartySelect } from "./PartySelect";
import type { Party } from "../types";

type OnlineCustomer = Shopper & { customer_party_id: string | null };

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
  const load = async () => {
    const [online, counter] = await Promise.all([
      accountRequest<{ items: OnlineCustomer[] }>("/online-customers", undefined, "parties"),
      api.billingCustomers(),
    ]);
    setItems(online.items); setParties(counter.items);
  };
  useEffect(() => { void load().catch(failure => setError(String(failure))); }, []);
  const link = async () => {
    if (!selected || !customer || !confirmed) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await accountRequest(`/online-customers/${selected.id}/link`, { method: "POST", body: JSON.stringify({ customer_party_id: customer }) }, "parties");
      setSelected(null); setMessage("Linked for future invoices. Past invoices and shopper orders are unchanged.");
      await load();
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const query = search.trim().toLowerCase();
  return <section className="ops-card"><h2>Online customer accounts</h2>
    <p>Online customers are separate from counter customers. Phone numbers are unverified. Only link after confirming the customer's identity directly.</p>
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <label>Search online customers<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, email or phone" /></label>
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Name</th><th>Email</th><th>Phone (unverified)</th><th>Counter link</th></tr></thead>
      <tbody>{items.filter(item => [item.display_name, item.email, item.phone].some(value => value?.toLowerCase().includes(query))).map(item =>
        <tr key={item.id}><td>{item.display_name}</td><td>{item.email}</td><td>{item.phone}</td><td>{item.customer_party_id ? "Linked" :
          <button className="ops-link-btn" type="button" disabled={busy} onClick={() => { setSelected(item); setCustomer(""); setConfirmed(false); setError(""); }}>Link manually</button>}</td></tr>)}</tbody>
    </table></div>
    {selected ? <fieldset disabled={busy}><legend>Link {selected.display_name} ({selected.email})</legend>
      <PartySelect parties={parties} value={customer} onChange={setCustomer} label="Counter customer" />
      <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I have confirmed this shopper and counter customer are the same person; a matching phone alone is not proof.</label>
      <button className="btn light" type="button" disabled={!customer || !confirmed || busy} onClick={() => void link()}>Confirm link</button>
      <button className="ops-link-btn" type="button" onClick={() => setSelected(null)}>Cancel</button>
    </fieldset> : null}
  </section>;
}

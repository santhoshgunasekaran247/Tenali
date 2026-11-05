import { FloatingAlert } from "./Notifications";
import { useState } from "react";
import { api } from "../api";
import type { Party } from "../types";
import { PartySelect } from "./PartySelect";

export function BillingCustomer({ parties, value, onChange, onCreated, disabled }: {
  parties: Party[]; value: string; onChange: (id: string) => void; onCreated: (party: Party) => void; disabled: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ legal_name: "", phone: "", email: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setError("");
    if (!form.legal_name.trim() || !form.phone.trim()) { setError("Enter the customer name and phone number."); return; }
    setBusy(true);
    try {
      const party = await api.createBillingCustomer({ ...form, party_type: "customer" });
      onCreated(party);
      setForm({ legal_name: "", phone: "", email: "" });
      setAdding(false);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to add customer."); }
    finally { setBusy(false); }
  };
  return <section>
    <PartySelect parties={parties} value={value} onChange={onChange} required disabled={disabled || busy} />
    <button type="button" className="ops-link-btn" disabled={disabled || busy} onClick={() => { setAdding(!adding); setError(""); }}>
      {adding ? "Cancel adding customer" : "Customer not found? Add customer here"}
    </button>
    {adding ? <fieldset disabled={disabled || busy}><legend>Add counter customer</legend>
      <label>Customer name<input value={form.legal_name} maxLength={150} onChange={event => setForm({ ...form, legal_name: event.target.value })} /></label>
      <label>Phone number<input type="tel" autoComplete="tel" value={form.phone} maxLength={40} onChange={event => setForm({ ...form, phone: event.target.value })} /></label>
      <label>Email (optional)<input type="email" value={form.email} maxLength={254} onChange={event => setForm({ ...form, email: event.target.value })} /></label>
      <p>Phone is recorded, not verified. Online accounts stay separate unless an administrator links them.</p>
      {error ? <FloatingAlert>{error}</FloatingAlert> : null}
      <button type="button" className="btn light" onClick={() => void save()}>{busy ? "Adding..." : "Add and select customer"}</button>
    </fieldset> : null}
  </section>;
}

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { SiteFooter } from "../components/SiteFooter";
import type { Party, PartyCreateInput, PartyType } from "../types";

const PARTY_TYPES: Array<{ value: PartyType; label: string }> = [
  { value: "customer", label: "Customer" },
  { value: "vendor", label: "Vendor" },
  { value: "customer_vendor", label: "Customer + Vendor" },
  { value: "employee", label: "Employee" },
  { value: "friend", label: "Friend" },
  { value: "other", label: "Other" },
];

type FormState = PartyCreateInput;

const INITIAL_FORM: FormState = {
  party_type: "customer",
  legal_name: "",
  nickname: "",
  contact_person: "",
  phone: "",
  email: "",
  address: "",
  gst_number: "",
};

export function PartiesPage() {
  const [items, setItems] = useState<Party[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [activeOnly, setActiveOnly] = useState(true);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function loadParties() {
    setLoading(true);
    setError(undefined);
    try {
      const response = await api.parties({ search: search.trim() || undefined, active_only: activeOnly });
      setItems(response.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load parties");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadParties();
  }, [activeOnly]);

  const title = useMemo(() => (editingId ? "Edit party" : "Add party"), [editingId]);

  function onEdit(party: Party) {
    setEditingId(party.id);
    setForm({
      party_type: party.party_type,
      legal_name: party.legal_name,
      nickname: party.nickname || "",
      contact_person: party.contact_person || "",
      phone: party.phone || "",
      email: party.email || "",
      address: party.address || "",
      gst_number: party.gst_number || "",
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetForm() {
    setEditingId(null);
    setForm(INITIAL_FORM);
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!form.legal_name.trim()) return;

    setSaving(true);
    setError(undefined);
    try {
      if (editingId) {
        await api.updateParty(editingId, {
          ...form,
          legal_name: form.legal_name.trim(),
        });
      } else {
        await api.createParty({
          ...form,
          legal_name: form.legal_name.trim(),
        });
      }
      resetForm();
      await loadParties();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save party");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <main className="ops-page">
        <section className="ops-hero">
          <p className="eyebrow">OPERATIONS · PARTIES</p>
          <h1>Customers and vendors</h1>
          <p>Capture and maintain your party master for billing, purchases, settlements and reporting.</p>
        </section>

        <section className="ops-grid">
          <article className="ops-card">
            <div className="ops-card-head">
              <h2>{title}</h2>
              {editingId && (
                <button className="ops-link-btn" type="button" onClick={resetForm}>
                  Cancel edit
                </button>
              )}
            </div>
            <form className="ops-form" onSubmit={onSubmit}>
              <label>
                Party type
                <select
                  value={form.party_type}
                  onChange={(event) => setForm((prev) => ({ ...prev, party_type: event.target.value as PartyType }))}
                >
                  {PARTY_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Legal name
                <input
                  required
                  value={form.legal_name}
                  onChange={(event) => setForm((prev) => ({ ...prev, legal_name: event.target.value }))}
                  placeholder="Acme Industries Pvt Ltd"
                />
              </label>
              <label>
                Nickname
                <input
                  value={form.nickname}
                  onChange={(event) => setForm((prev) => ({ ...prev, nickname: event.target.value }))}
                  placeholder="Acme"
                />
              </label>
              <label>
                Contact person
                <input
                  value={form.contact_person}
                  onChange={(event) => setForm((prev) => ({ ...prev, contact_person: event.target.value }))}
                  placeholder="Ravi Kumar"
                />
              </label>
              <label>
                Phone
                <input
                  value={form.phone}
                  onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
                  placeholder="+91..."
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
                  placeholder="name@company.com"
                />
              </label>
              <label>
                GST number
                <input
                  value={form.gst_number}
                  onChange={(event) => setForm((prev) => ({ ...prev, gst_number: event.target.value }))}
                  placeholder="29ABCDE1234F1Z5"
                />
              </label>
              <label>
                Address
                <textarea
                  value={form.address}
                  onChange={(event) => setForm((prev) => ({ ...prev, address: event.target.value }))}
                  rows={3}
                  placeholder="Full business address"
                />
              </label>
              <button className="btn" type="submit" disabled={saving}>
                {saving ? "Saving..." : editingId ? "Update party" : "Create party"}
              </button>
            </form>
          </article>

          <article className="ops-card ops-list-card">
            <div className="ops-card-head">
              <h2>Party list</h2>
            </div>
            <div className="ops-list-tools">
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by name, nickname or phone"
              />
              <label className="ops-toggle">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(event) => setActiveOnly(event.target.checked)}
                />
                Active only
              </label>
              <button className="btn" type="button" onClick={loadParties} disabled={loading}>
                {loading ? "Loading..." : "Refresh"}
              </button>
            </div>
            {error && <p className="ops-error">{error}</p>}
            <div className="ops-table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Contact</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((party) => (
                    <tr key={party.id}>
                      <td>
                        <strong>{party.legal_name}</strong>
                        <div>{party.nickname || "-"}</div>
                      </td>
                      <td>{party.party_type}</td>
                      <td>
                        <div>{party.phone || "-"}</div>
                        <div>{party.email || "-"}</div>
                      </td>
                      <td>{party.is_active ? "Active" : "Inactive"}</td>
                      <td>
                        <button className="ops-link-btn" type="button" onClick={() => onEdit(party)}>
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!items.length && !loading && (
                    <tr>
                      <td colSpan={5}>No parties found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </article>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

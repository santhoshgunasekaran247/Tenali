import { CursorPagination } from "../components/CursorPagination";
import { FloatingAlert } from "../components/Notifications";
import { useDraftState } from "../features/drafts";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { contactsPage } from "../features/partiesPagination";
import { SiteFooter } from "../components/SiteFooter";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";
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
  const { user } = useAuth();
  const [items, setItems] = useState<Party[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [activeOnly, setActiveOnly] = useState(true);
  const [form, setForm] = useDraftState<FormState>("PartiesPage.form", INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useDraftState<string | null>("PartiesPage.editingId", null);
  const [size, setSize] = useState(25);
  const [page, setPage] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [next, setNext] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    setItems([]);
    setNext(null);
    contactsPage(search, activeOnly, size, cursors[page]).then(response => {
      if (active) { setItems(response.items); setNext(response.next_cursor); }
    }).catch(e => {
      if (active) setLoadError(e instanceof Error ? e.message : "Failed to load contacts");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [search, activeOnly, size, page, cursors, revision]);

  function resetPage() { setPage(0); setCursors([null]); }
  function refresh() { setRevision(value => value + 1); }

  const title = useMemo(() => (editingId ? "Edit contact" : "Add contact"), [editingId]);

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
      resetPage();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save contact");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <main className="ops-page">
        <section className="ops-hero">
          <PortalHomeLink />
          <p className="eyebrow">OPERATIONS · CONTACTS</p>
          <h1>Contacts</h1>
          <p>Manage customers, vendors and other business contacts for billing, purchases, settlements and reporting.</p>
        </section>
        {user && ["owner", "admin"].includes(user.role) ? <p><Link className="ops-inline-link" to="/portal/online-customers">Manage online customer accounts separately</Link></p> : null}

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
                Contact type
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
                  type="tel"
                  required={form.party_type === "customer" || form.party_type === "customer_vendor"}
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
                {saving ? "Saving..." : editingId ? "Update contact" : "Create contact"}
              </button>
            </form>
          </article>

          <article className="ops-card ops-list-card">
            <div className="ops-card-head">
              <h2>Contact list</h2>
            </div>
            <div className="ops-list-tools">
              <input
                value={search}
                onChange={(event) => { setSearch(event.target.value); resetPage(); }}
                placeholder="Search by name, nickname or phone"
              />
              <label className="ops-toggle">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(event) => { setActiveOnly(event.target.checked); resetPage(); }}
                />
                Active only
              </label>
              <button className="btn" type="button" onClick={refresh} disabled={loading}>
                {loading ? "Loading..." : "Refresh"}
              </button>
              <button type="button" onClick={() => { setSearch(""); setActiveOnly(true); resetPage(); }}>Reset filters</button>
            </div>
            {error && <FloatingAlert>{error}</FloatingAlert>}
            {loadError && <><FloatingAlert>{loadError}</FloatingAlert><button type="button" onClick={refresh}>Retry</button></>}
            {loading && <p role="status">Loading contacts...</p>}
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
                  {!items.length && !loading && !loadError && (
                    <tr>
                      <td colSpan={5}>No contacts found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <CursorPagination size={size} page={page} hasNext={!!next} busy={loading} onSize={value => { setSize(value); resetPage(); }}
              onPrevious={() => setPage(value => value - 1)} onNext={() => { if (next) { setCursors(values => [...values.slice(0, page + 1), next]); setPage(value => value + 1); } }} />
          </article>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

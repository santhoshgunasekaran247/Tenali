import { FloatingAlert } from "./Notifications";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PolicyDocument } from "./PolicyDocument";
import { policyAdminPath, policyPath, policyRequest, type PolicyContent, type PolicyDraft, type PolicyKind, type PolicyScope } from "../features/policies";

export function PolicyEditor({ scope }: { scope: PolicyScope }) {
  const [items, setItems] = useState<PolicyDraft[]>([]);
  const [selected, setSelected] = useState<PolicyKind | "">("");
  const [content, setContent] = useState<PolicyContent | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [retry, setRetry] = useState(0);
  const current = items.find(item => item.kind === selected);
  const dirty = !!current && JSON.stringify(content) !== JSON.stringify(current.content);
  const endpoint = policyAdminPath(scope);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setMessage(""); setReviewed(false);
    policyRequest<{ items: PolicyDraft[] }>(endpoint).then(result => {
      if (!active) return;
      setItems(result.items); setSelected(result.items[0]?.kind || ""); setContent(result.items[0]?.content || null);
    }).catch(failure => { if (active) setError(String(failure)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [endpoint, retry]);
  const accept = (result: PolicyDraft) => {
    setItems(previous => previous.map(item => item.kind === result.kind ? result : item));
    setContent(result.content); setReviewed(false);
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!current || !content) return;
    setBusy(true); setError(""); setMessage("");
    try {
      accept(await policyRequest<PolicyDraft>(`${endpoint}/${selected}`, {
        method: "PUT", body: JSON.stringify({ revision: current.revision, content }),
      }));
      setMessage("Draft saved. The public policy has not changed.");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const publish = async () => {
    if (!current || dirty || !reviewed) return;
    setBusy(true); setError(""); setMessage("");
    try {
      accept(await policyRequest<PolicyDraft>(`${endpoint}/${selected}/publish`, {
        method: "POST", body: JSON.stringify({ revision: current.revision, reviewed }),
      }));
      setMessage("Policy published. This version is now public.");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const update = (key: keyof Omit<PolicyContent, "currency">, value: string) => {
    setContent(previous => previous ? { ...previous, [key]: value } : previous);
    setReviewed(false); setMessage("");
  };
  return <section className="policy-editor">
    <h2>{scope === "platform" ? "Platform policies" : "Store policies"}</h2>
    <p>Original templates are starting points, not legal advice or provider approval. Review actual practices, full postal address, contacts and every [[...]] placeholder before publishing. Authentication disclosures belong in privacy and terms; sign-in behavior is unchanged.</p>
    <p>All prices and payments are in INR. Published versions remain unchanged when you edit a draft. Publication makes the contact email public; replace the suggested login email if a separate support address is needed.</p>
    {scope === "platform" ? <p className="checkout-notice">Confirm the supplied address &quot;Chennai 100&quot; includes the correct full postal code before publishing.</p> : null}
    <p><Link to={policyPath(scope)}>View public policy index</Link></p>
    {loading ? <p role="status">Loading policy drafts...</p> : null}
    {error ? <FloatingAlert><p>{error}</p><button type="button" className="ops-link-btn" disabled={busy || dirty} onClick={() => setRetry(value => value + 1)}>Reload latest drafts</button>{dirty ? <p>Copy unsaved work first, then discard edits to reload.</p> : null}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {!loading && current && content ? <>
      <label className="policy-selector">Policy<select disabled={busy || dirty} value={selected} onChange={event => {
        const next = items.find(item => item.kind === event.target.value);
        if (next) { setSelected(next.kind); setContent(next.content); setReviewed(false); setMessage(""); setError(""); }
      }}>{items.map(item => <option key={item.kind} value={item.kind}>{item.content.title}{item.published ? " (published)" : " (draft only)"}</option>)}</select></label>
      <p>Draft version {current.revision || "not saved"} · {current.published_at ? `Public version ${current.published_revision}, published ${new Date(current.published_at).toLocaleString()}` : "Not published"}</p>
      <form className="ops-form ops-card" onSubmit={save}><fieldset className="access-fields" disabled={busy}>
        <legend>Edit draft</legend>
        <div className="company-fields">
          <label>Policy title<input required maxLength={160} value={content.title} onChange={event => update("title", event.target.value)} /></label>
          <label>Legal/trading business name<input maxLength={200} value={content.business_name} onChange={event => update("business_name", event.target.value)} /></label>
          <label>Public support/privacy email<input type="email" maxLength={254} value={content.contact_email} onChange={event => update("contact_email", event.target.value)} /></label>
          <label>Jurisdiction<input maxLength={200} value={content.jurisdiction} onChange={event => update("jurisdiction", event.target.value)} /></label>
          <label className="company-field-wide">Business address, including full postal code<textarea rows={3} maxLength={1500} value={content.address} onChange={event => update("address", event.target.value)} /></label>
        </div>
        <label>Policy text (plain text; no HTML)<textarea className="policy-text-input" required rows={22} maxLength={50000} value={content.body} onChange={event => update("body", event.target.value)} /></label>
        <div className="shop-actions"><button className="btn" disabled={busy || (!dirty && current.revision > 0)}>Save draft</button><button className="btn light" type="button" disabled={busy || !dirty} onClick={() => { setContent(current.content); setReviewed(false); setError(""); setMessage(""); }}>Discard unsaved edits</button></div>
      </fieldset></form>
      <details className="ops-card" open><summary>Draft preview (not public)</summary><PolicyDocument content={content} /></details>
      {current.published ? <details className="ops-card"><summary>Currently published version</summary><PolicyDocument content={current.published} /><Link to={policyPath(scope, current.kind)}>Open public page</Link></details> : null}
      <section className="ops-card"><h3>Publish reviewed policy</h3>
        {dirty ? <p>Save your changes before publishing or switching policies.</p> : current.issues.length ? <ul className="ops-error">{current.issues.map(issue => <li key={issue}>{issue}</li>)}</ul> : <p>Required fields are complete. This check is not a legal or integration-compliance review.</p>}
        <label className="ops-toggle"><input type="checkbox" checked={reviewed} disabled={busy || dirty || !current.revision || !!current.issues.length} onChange={event => setReviewed(event.target.checked)} />I have reviewed this policy and contact details for my business, replaced all placeholders, and confirmed the stated practices and commercial terms.</label>
        <button className="btn" type="button" disabled={busy || dirty || !reviewed || !current.revision || !!current.issues.length || current.published_revision === current.revision} onClick={() => void publish()}>Publish this version</button>
      </section>
    </> : null}
  </section>;
}

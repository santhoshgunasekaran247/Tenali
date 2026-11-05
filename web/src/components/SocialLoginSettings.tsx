import { FloatingAlert } from "./Notifications";
import { FormEvent, useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { ExternalLink, KeyRound, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

type Settings = { supabase_url: string; public_key: string; providers: string[]; enabled: boolean };
const OPTIONS = [["google", "Google", "Google OAuth client"], ["facebook", "Facebook", "Meta developer application"], ["custom:yahoo", "Yahoo", "Custom provider: custom:yahoo"], ["azure", "Microsoft", "Microsoft Entra application"], ["apple", "Apple", "Apple developer configuration"]];

export function SocialLoginSettings() {
  const [form, setForm] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedEnabled, setSavedEnabled] = useState(false);
  const projectRef = form?.supabase_url.match(/^https:\/\/([a-z0-9]{20})\.supabase\.co\/?$/)?.[1];
  useEffect(() => {
    void accountRequest<Settings>("/social-login", undefined, "platform").then(settings => {
      setForm(settings); setSavedEnabled(settings.enabled);
    }).catch(failure => setError(String(failure)));
  }, []);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await accountRequest<{ message: string }>("/social-login", { method: "PUT", body: JSON.stringify(form) }, "platform");
      setMessage(result.message);
      setSavedEnabled(form?.enabled ?? false);
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="authentication-settings" id="social-login">
    <div className="platform-section-title"><div className="settings-title-row"><div><h2>Social login</h2><p>Connect Supabase once. Use it for shopper accounts and workspace owner sign-in.</p></div><span className={`platform-status ${savedEnabled ? "is-enabled" : ""}`}>{!form ? "Loading settings" : savedEnabled ? "Enabled in Tenali" : "Not enabled"}</span></div></div>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <div className="authentication-settings-layout">
    <div>{!form ? <p role="status">{error ? "Settings could not be loaded. Refresh to retry." : "Loading social login settings..."}</p> : <form className="ops-form authentication-form" onSubmit={save}><fieldset disabled={busy} className="authentication-fields">
      <section className="settings-card"><h3><KeyRound size={18}/>Project connection</h3><p className="social-caption">Use the same Supabase project as your database. Only public configuration belongs here.</p>
        <label>Supabase Project URL<input required type="url" maxLength={253} placeholder="https://your-project-ref.supabase.co" value={form.supabase_url} onChange={event => setForm({ ...form, supabase_url: event.target.value.trim() })} /></label>
        <label>Supabase Publishable / Anon Key (public)<textarea required={form.enabled} rows={3} maxLength={2000} spellCheck={false} autoCapitalize="none" value={form.public_key} onChange={event => setForm({ ...form, public_key: event.target.value.trim() })} /><span className="social-caption">From Supabase Project Settings → API Keys. Never use a secret or service-role key.</span></label>
      </section>
      <fieldset className="settings-card provider-settings"><legend>Sign-in providers</legend><p className="social-caption">Select only providers you have enabled and configured in Supabase.</p><div className="provider-settings-grid">{OPTIONS.map(([id, label, detail]) => <label className={`provider-choice ${form.providers.includes(id) ? "is-selected" : ""}`} key={id}>
        <input type="checkbox" checked={form.providers.includes(id)} onChange={event => setForm({ ...form, providers: event.target.checked ? [...form.providers, id] : form.providers.filter(value => value !== id) })} /><span><strong>{label}</strong><small>{detail}</small></span>
      </label>)}</div></fieldset>
      <section className="settings-card"><label className="authentication-enable"><input type="checkbox" checked={form.enabled} onChange={event => setForm({ ...form, enabled: event.target.checked })} /><span><strong>Enable social login</strong><small>Allow new shopper and workspace-owner social sign-ins.</small></span></label><p className="social-caption">Existing staff/platform passwords stay unchanged. Disabling does not revoke existing sessions.</p></section>
      <div className="settings-save-bar"><p>Applies to all tenants. Project changes are locked once social accounts exist.</p><button className="btn" disabled={busy || !form.providers.length}>{busy ? "Saving..." : "Save authentication settings"}</button></div>
    </fieldset></form>}</div>
    <aside className="settings-help settings-card"><h3><ShieldCheck size={18}/>Setup checklist</h3>
      <p><Link to="/platform/policies">Review and publish platform policies</Link> before submitting an OAuth app. Use the published privacy, terms and account/data-deletion URLs; provider approval and any required deletion callback remain separate.</p>
      <ol><li><strong>Configure your providers</strong><p>Google needs an OAuth Client ID and Secret. Enter these in Supabase, not Tenali. Yahoo needs custom:yahoo.</p></li><li><strong>Allow return URLs</strong><p>In Supabase Authentication → URL Configuration, allow each origin's <code>/social-login?**</code> callback.</p></li><li><strong>Connect and test</strong><p>Save public settings here, then test in a browser with popups allowed. No phone OTP or SMS is enabled.</p></li></ol>
      <a className="settings-external-link" href={projectRef ? `https://supabase.com/dashboard/project/${projectRef}/auth/providers` : "https://supabase.com/dashboard"} target="_blank" rel="noreferrer">Open Supabase providers<ExternalLink size={14}/></a>
      <p className="social-caption">Saving is not a connection test. It does not configure providers, approve OAuth apps, or activate paid services.</p>
    </aside></div>
  </section>;
}

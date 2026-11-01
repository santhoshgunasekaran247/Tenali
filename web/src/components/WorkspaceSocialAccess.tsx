import { FormEvent, useEffect, useState } from "react";
import { authRequest, type Identity, useAuth } from "../features/auth";
import { tenantSlug } from "../features/tenantTransport";
import type { FederationConfig, SocialUser } from "../features/shopperFederation";
import { socialLogin } from "../features/shopperFederation";
import { SocialProviderButtons } from "./SocialProviderButtons";

export function WorkspaceSocialAccess({ register = false, workspaceSlug }: { register?: boolean; workspaceSlug?: string }) {
  const auth = useAuth();
  const [config, setConfig] = useState<FederationConfig | null>(null);
  const [social, setSocial] = useState<SocialUser | null>(null);
  const [form, setForm] = useState({ company_name: "", slug: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const slug = tenantSlug() || auth.storefront?.tenant_slug || workspaceSlug || form.slug;
  useEffect(() => {
    let active = true;
    authRequest<FederationConfig>("/social-config").then(result => { if (active) setConfig(result); }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, []);
  const login = async (provider: string) => {
    if (!config) return;
    if (!register && !slug) { setError("Enter your workspace address first."); return; }
    setBusy(true); setError("");
    try {
      const user = await socialLogin(config, provider);
      if (register) setSocial(user);
      else {
        const result = await authRequest<{ user: Identity }>("/login-social", {
          method: "POST", headers: { "X-Tenant-Slug": slug }, body: JSON.stringify({ id_token: await user.getIdToken() }),
        });
        window.location.assign(`/c/${result.user.tenant_slug}/portal`);
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to sign in."); }
    finally { setBusy(false); }
  };
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!social) return;
    setBusy(true); setError("");
    try {
      const result = await authRequest<{ user: Identity }>("/register-social", {
        method: "POST", headers: { "X-Tenant-Slug": "" },
        body: JSON.stringify({ ...form, id_token: await social.getIdToken() }),
      });
      window.location.assign(`/c/${result.user.tenant_slug}/portal/company`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to create workspace."); setBusy(false); }
  };
  return <section className="workspace-social-access" aria-label={register ? "Create workspace" : "Owner social sign-in"}>
    <div className="social-section-heading"><h2>{register ? "Start with your social account" : "Workspace owner sign-in"}</h2>
      <p>{register ? "A verified identity for your new business workspace." : "Use the social account you used to create this workspace."}</p></div>
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {!config ? <p className="social-caption" role="status">{error ? "Sign-in options could not be loaded. Refresh to retry." : "Loading sign-in options..."}</p> : !config.enabled ? <p className="social-setup-notice" role="status">Social sign-in is not available yet. {register ? <>Ask the platform administrator to complete <a href="/platform/authentication">authentication setup</a>.</> : "Existing staff can sign in with their password below."}</p> : <>
      {!register && !tenantSlug() && !auth.storefront && workspaceSlug === undefined ? <label className="social-workspace-label">Workspace address<input value={form.slug} maxLength={48} onChange={event => setForm({ ...form, slug: event.target.value.toLowerCase().trim() })} /></label> : null}
      {register && social ? <form className="ops-form" onSubmit={create}><fieldset disabled={busy} className="access-fields">
        <p>Signed in with {social.email}. The server obtains your email from the social provider; it cannot be typed or substituted here.</p>
        <label>Company Name<input required maxLength={200} autoComplete="organization" value={form.company_name} onChange={event => setForm({ ...form, company_name: event.target.value })} /></label>
        <label>Workspace Address<input required minLength={3} maxLength={48} pattern="[a-z0-9](?:[a-z0-9]|-){1,46}[a-z0-9]" value={form.slug} onChange={event => setForm({ ...form, slug: event.target.value.toLowerCase() })} /></label>
        <button className="btn" disabled={busy}>{busy ? "Creating..." : "Create Workspace"}</button>
        <button className="ops-link-btn" type="button" disabled={busy} onClick={() => setSocial(null)}>Use another social account</button>
      </fieldset></form> : <SocialProviderButtons providers={config.providers} busy={busy} onLogin={provider => void login(provider)} />}
      <p className="social-caption">{register ? "No new password to remember. Your workspace and shopper accounts stay separate." : "Social sign-in does not grant access to another workspace."}</p>
    </>}
  </section>;
}

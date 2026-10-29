import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { accountRequest } from "../features/shop";
import { tenantBase, tenantFetch } from "../features/tenantTransport";

type Admin = { id: string; email: string; display_name: string };
type Workspace = { id: string; company_name: string; tenant_slug: string; is_active: boolean };
export function PlatformAdminPage() {
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const unavailable = !!tenantBase();
  const refresh = async () => setWorkspaces((await accountRequest<{ items: Workspace[] }>(`/workspaces?offset=${offset}`, undefined, "platform")).items);
  useEffect(() => {
    if (unavailable) { setChecking(false); return; }
    let active = true;
    tenantFetch("/api/platform/session", { headers: { "X-Tenant-Slug": "" } }).then(async response => {
      if (response.status === 401) return;
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Unable to load platform session");
      if (active) setAdmin(body);
    }).catch(failure => { if (active) setError(String(failure)); }).finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [unavailable]);
  useEffect(() => { if (admin) void refresh().catch(failure => setError(String(failure))); }, [admin?.id, offset]);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { setAdmin(await accountRequest<Admin>("/login", { method: "POST", body: JSON.stringify(form) }, "platform")); setForm({ email: "", password: "" }); }
    catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  return <main className="shop-account-page"><header className="shop-account-heading"><h1>Platform Superadmin</h1><p>Platform operator credentials only. Workspace staff and shopper logins cannot access this console.</p><Link to="/">Back to Platform</Link></header><div className="shop-account-content">
    {unavailable ? <p>Open the platform host without a workspace path to use this console.</p> : checking ? <p>Checking platform session...</p> : <>
      {error ? <p className="ops-error" role="alert">{error}</p> : null}
      {!admin ? <form className="ops-form access-panel" onSubmit={submit}><label>Platform Email<input type="email" required autoComplete="username" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label><label>Platform Password<input type="password" required maxLength={128} autoComplete="current-password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} /></label><button className="btn" disabled={busy}>Sign In as Platform Administrator</button></form> : <>
        <p>{admin.display_name} · {admin.email}</p><button className="btn light" disabled={busy} onClick={() => {
          setBusy(true); setError("");
          void accountRequest("/logout", { method: "POST" }, "platform").then(() => { setAdmin(null); setWorkspaces([]); })
            .catch(failure => setError(String(failure))).finally(() => setBusy(false));
        }}>Sign Out of Platform</button>
        <h2>Workspaces</h2><p>Disabling a workspace revokes its staff and shopper sessions and hides its storefront. This console does not expose provider secrets or allow staff impersonation.</p>
        {workspaces.map(workspace => <article key={workspace.id} className="ops-card shop-order"><h3>{workspace.company_name}</h3><p>{workspace.tenant_slug} · {workspace.is_active ? "Active" : "Disabled"}</p><button disabled={busy} className="btn light" onClick={() => {
          setBusy(true); setError("");
          void accountRequest(`/workspaces/${workspace.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !workspace.is_active }) }, "platform")
            .then(refresh).catch(failure => setError(String(failure))).finally(() => setBusy(false));
        }}>{workspace.is_active ? "Disable Workspace" : "Enable Workspace"}</button></article>)}
        <div className="shop-actions"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button disabled={workspaces.length < 50 || busy} onClick={() => setOffset(offset + 50)}>Next</button></div>
      </>}
    </>}
  </div></main>;
}

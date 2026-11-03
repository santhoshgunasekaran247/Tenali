import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Building2, ShieldCheck, LogOut } from "lucide-react";
import { accountRequest } from "../features/shop";
import { tenantBase, tenantFetch } from "../features/tenantTransport";
import { SocialLoginSettings } from "../components/SocialLoginSettings";
import { PolicyEditor } from "../components/PolicyEditor";
import { useAuth } from "../features/auth";

type Admin = { id: string; email: string; display_name: string };
type Workspace = { id: string; company_name: string; tenant_slug: string; is_active: boolean };
export function PlatformAdminPage() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const authentication = location.pathname === "/platform/authentication";
  const policies = location.pathname === "/platform/policies";
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [denied, setDenied] = useState(false);
  const unavailable = !!tenantBase() || !!auth.user || !!auth.storefront || denied;
  const refresh = async () => setWorkspaces((await accountRequest<{ items: Workspace[] }>(`/workspaces?offset=${offset}`, undefined, "platform")).items);
  useEffect(() => {
    if (auth.loading) return;
    if (unavailable) { setChecking(false); return; }
    let active = true;
    tenantFetch("/api/platform/session", { headers: { "X-Tenant-Slug": "" } }).then(async response => {
      if (response.status === 401) return;
      if (response.status === 403) { if (active) setDenied(true); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Unable to load platform session");
      if (active) setAdmin(body);
    }).catch(failure => { if (active) setError(String(failure)); }).finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [unavailable, auth.loading]);
  useEffect(() => {
    if (location.hash === "#social-login") navigate("/platform/authentication", { replace: true });
  }, [location.hash, navigate]);
  useEffect(() => { if (admin && !authentication && !policies) void refresh().catch(failure => setError(String(failure))); }, [admin?.id, offset, authentication, policies]);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { setAdmin(await accountRequest<Admin>("/login", { method: "POST", body: JSON.stringify(form) }, "platform")); setForm({ email: "", password: "" }); }
    catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  return <main className="platform-console"><header className="platform-console-header"><div><span className="platform-eyebrow">TENALI PLATFORM</span><h1>{policies ? "Public policies" : authentication ? "Authentication" : "Client administration"}</h1><p>{policies ? "Review and publish Tenali platform policies." : authentication ? "One secure sign-in configuration for every workspace and storefront." : "Manage client workspaces and their availability."}</p></div><Link to="/">Back to platform</Link></header><div className="platform-console-body">
    {auth.loading ? <p>Checking access...</p> : unavailable ? <section className="settings-card" role="alert"><h2>Platform access restricted</h2><p>Tenant and shopper accounts cannot access platform administration. Use your Operations Portal for workspace tasks.</p>{auth.user ? <Link className="btn" to="/portal">Go to Operations Portal</Link> : <Link to="/login">Back to workspace sign-in</Link>}</section> : checking ? <p>Checking platform session...</p> : <>
      {error ? <p className="ops-error" role="alert">{error}</p> : null}
      {!admin ? <form className="ops-form access-panel platform-login" onSubmit={submit}><ShieldCheck size={30}/><h2>Platform administrator sign-in</h2><p>Use your platform credentials. Client and shopper accounts cannot access this console.</p><label>Platform Email<input type="email" required autoComplete="username" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label><label>Platform Password<input type="password" required maxLength={128} autoComplete="current-password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} /></label><button className="btn" disabled={busy}>Sign In as Platform Administrator</button></form> : <div className="platform-layout">
        <aside className="platform-sidebar"><nav aria-label="Platform sections"><Link to="/platform" aria-current={!authentication && !policies ? "page" : undefined}><Building2 size={18}/>Client administration</Link><Link to="/platform/authentication" aria-current={authentication ? "page" : undefined}><ShieldCheck size={18}/>Authentication</Link><Link to="/platform/policies" aria-current={policies ? "page" : undefined}><ShieldCheck size={18}/>Public policies</Link></nav>
        <div className="platform-operator"><strong>{admin.display_name}</strong><span>{admin.email}</span><button className="ops-link-btn" disabled={busy} onClick={() => {
          setBusy(true); setError("");
          void accountRequest("/logout", { method: "POST" }, "platform").then(() => { setAdmin(null); setWorkspaces([]); })
            .catch(failure => setError(String(failure))).finally(() => setBusy(false));
        }}><LogOut size={15}/>Sign out</button></div></aside>
        <div className="platform-section">{policies ? <PolicyEditor key={admin.id} scope="platform" /> : authentication ? <SocialLoginSettings key={admin.id} /> : <section aria-labelledby="platform-clients-heading">
        <div className="platform-section-title"><h2 id="platform-clients-heading">Client workspaces</h2><p>Disabling a client hides its storefront and revokes its staff and shopper sessions.</p></div>
        <div className="platform-client-list">{workspaces.map(workspace => <article key={workspace.id} className="platform-client-card"><div><h3>{workspace.company_name}</h3><p>{workspace.tenant_slug}</p></div><span className={`platform-status ${workspace.is_active ? "is-enabled" : ""}`}>{workspace.is_active ? "Active" : "Disabled"}</span><button disabled={busy} className="btn light" onClick={() => {
          setBusy(true); setError("");
          void accountRequest(`/workspaces/${workspace.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !workspace.is_active }) }, "platform")
            .then(refresh).catch(failure => setError(String(failure))).finally(() => setBusy(false));
        }}>{workspace.is_active ? "Disable Workspace" : "Enable Workspace"}</button></article>)}</div>
        {!workspaces.length ? <p className="social-caption">No client workspaces on this page.</p> : null}
        <div className="shop-actions"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button disabled={workspaces.length < 50 || busy} onClick={() => setOffset(offset + 50)}>Next</button></div>
        </section>}</div>
      </div>}
    </>}
  </div></main>;
}

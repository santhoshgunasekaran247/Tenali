import { useDraftState } from "../features/drafts";
import { FloatingAlert } from "../components/Notifications";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { CheckCircle, Copy, Globe, RefreshCw, Trash2 } from "lucide-react";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { authRequest, useAuth } from "../features/auth";

type HostingStatus = "manual" | "dns_pending" | "provisioning" | "tls_pending" | "active" | "error" | "removing";
type DnsRecord = { type: string; name: string; value: string };
type Domain = {
  id: string; hostname: string; verification_token: string; verified_at: string | null;
  hosting_status: HostingStatus; hosting_error: string | null; dns_records?: DnsRecord[];
};
type Domains = { items: Domain[]; cname_target: string; base_domain: string; automatic_hosting: boolean };
const labels: Record<HostingStatus, string> = {
  manual: "Manual hosting", dns_pending: "Waiting for DNS", provisioning: "Configuring Render",
  tls_pending: "Waiting for DNS / HTTPS", active: "Active", error: "Action required", removing: "Removing hosting",
};

export function DomainsPage() {
  const auth = useAuth();
  const [data, setData] = useState<Domains>({ items: [], cname_target: "", base_domain: "", automatic_hosting: false });
  const [host, setHost] = useDraftState("DomainsPage.host", "");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => setData(await authRequest<Domains>("/domains")), [auth.user?.company_id]);
  useEffect(() => { void load().catch(failure => setError(String(failure))); }, [load]);
  const pending = data.items.some(domain => !["manual", "active"].includes(domain.hosting_status));
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      void load().catch(failure => setError(String(failure)));
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load, pending]);
  if (!auth.user || !["owner", "admin"].includes(auth.user.role)) return <main className="loading">Administrator access required.</main>;

  const add = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      setData(await authRequest<Domains>("/domains", { method: "POST", body: JSON.stringify({ hostname: host }) }));
      setHost(""); setMessage("Domain added. Copy the DNS records below into your DNS provider.");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const verify = async (domain: Domain) => {
    setBusy(true); setError(""); setMessage("");
    try {
      setData(await authRequest<Domains>(`/domains/${domain.id}/verify`, { method: "POST" }));
      setMessage(data.automatic_hosting
        ? "Ownership verified. Tenali will configure Render and check HTTPS automatically; you can close this page."
        : "Ownership verified. Hosting and HTTPS still require platform configuration.");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const remove = async (domain: Domain) => {
    if (!confirm(`Remove ${domain.hostname} and its managed hosting? Update DNS afterwards to avoid leaving unused records.`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await authRequest<{ removing: boolean; retained_hosting: string[] }>(`/domains/${domain.id}`, { method: "DELETE" });
      await load();
      setMessage((result.removing ? "Domain disabled. Render cleanup will complete automatically." : "Domain removed.") +
        (result.retained_hosting.length ? ` Pre-existing externally managed Render entries were retained: ${result.retained_hosting.join(", ")}.` : ""));
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const copy = (value: string) => {
    void navigator.clipboard.writeText(value).catch(() => setError("Copy was unavailable; select the value manually."));
  };

  return <main className="ops-page masters-page">
    <header className="masters-heading"><PortalHomeLink /><h1>Storefront Domains</h1></header>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <section className="ops-grid ops-grid-single">
      <article className="ops-card">
        <h2>Your storefront</h2>
        <a href={`/c/${auth.user.tenant_slug}`}>{location.origin}/c/{auth.user.tenant_slug}</a>
        {data.automatic_hosting
          ? <p>Add your own domain and update its DNS. Tenali handles Render registration and HTTPS automatically. No Render account is needed.</p>
          : <p>Automatic hosting is not enabled. Ownership verification alone does not configure hosting or HTTPS.</p>}
      </article>
      <article className="ops-card">
        <form className="ops-form" onSubmit={add}>
          <label>Custom domain<input required placeholder="sourcedbysru.in" maxLength={245} value={host} onChange={event => setHost(event.target.value)} /></label>
          {data.automatic_hosting ? <p>Enter the storefront hostname without www. or api. Tenali also reserves its www alias and a separate api hostname. Do not use a domain already serving another website unless you intend to replace it.</p> : null}
          <button className="btn" disabled={busy}><Globe size={16} />Add domain</button>
        </form>
      </article>
      {data.items.map(domain => <article className="ops-card domain-entry" key={domain.id}>
        <div className="ops-card-head"><h2>{domain.hostname}</h2><strong role="status">{labels[domain.hosting_status]}</strong></div>
        {domain.hosting_error ? <p role="alert">{domain.hosting_error}</p> : null}
        {domain.hosting_status === "active"
          ? <p><a href={`https://${domain.hostname}`} target="_blank" rel="noreferrer">Open storefront</a></p> : null}
        <p>{domain.verified_at ? "Domain ownership verified." : "Add the TXT record to prove ownership."}</p>
        {domain.dns_records?.length ? <>
          <p>At your DNS provider, add these records. Names below are full hostnames. In GoDaddy, use @ for the registered domain itself, or remove your registered domain suffix from the Name field (for example: www, api, _tenali-verification).</p>
          <div className="table-responsive"><table>
            <thead><tr><th>Type</th><th>Full record name</th><th>Value</th><th>Copy</th></tr></thead>
            <tbody>{domain.dns_records.map(record => <tr key={record.type + record.name}>
              <td>{record.type}</td><td style={{ overflowWrap: "anywhere" }}>{record.name}</td>
              <td style={{ overflowWrap: "anywhere" }}>{record.value}</td>
              <td><button className="ops-link-btn" aria-label={`Copy ${record.type} value for ${record.name}`} onClick={() => copy(record.value)}><Copy size={16} /></button></td>
            </tr>)}</tbody>
          </table></div>
          <p>Keep existing email records. Replace conflicting website records only; remove conflicting website AAAA records and domain forwarding. DNS and certificate changes can take time. Your existing Tenali workspace address remains available.</p>
        </> : <dl>
          <div><dt>TXT record name</dt><dd><code>_tenali-verification.{domain.hostname}</code></dd></div>
          <div><dt>TXT record value</dt><dd><code>{domain.verification_token}</code><button className="ops-link-btn" aria-label={`Copy token for ${domain.hostname}`} onClick={() => copy(domain.verification_token)}><Copy size={16} /></button></dd></div>
          <div><dt>CNAME target</dt><dd>{data.cname_target || "Platform deployment target is not configured yet."}</dd></div>
        </dl>}
        <div className="reports-actions-row">
          <button className="btn" disabled={busy || domain.hosting_status === "removing"} onClick={() => void verify(domain)}><CheckCircle size={16} />{data.automatic_hosting ? "Verify & connect" : "Verify DNS"}</button>
          <button className="ops-link-btn" disabled={busy} onClick={() => void load().catch(failure => setError(String(failure)))}><RefreshCw size={16} />Refresh status</button>
          <button className="ops-link-btn" disabled={busy || domain.hosting_status === "removing"} aria-label={`Remove ${domain.hostname}`} onClick={() => void remove(domain)}><Trash2 size={16} /></button>
        </div>
      </article>)}
    </section>
  </main>;
}

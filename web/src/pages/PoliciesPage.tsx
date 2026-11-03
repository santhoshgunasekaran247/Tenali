import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PolicyDocument } from "../components/PolicyDocument";
import { useAuth } from "../features/auth";
import { policyPath, policyRequest, type PolicyScope, type PolicySummary, type PublicPolicy } from "../features/policies";
import { tenantBase } from "../features/tenantTransport";

export function PoliciesPage() {
  const { scope: scopeParam, kind } = useParams();
  const { storefront, loading: authLoading } = useAuth();
  const scope: PolicyScope = scopeParam === "tenant" || (!scopeParam && (storefront || tenantBase())) ? "tenant" : "platform";
  const validScope = !scopeParam || scopeParam === "platform" || scopeParam === "tenant";
  const [items, setItems] = useState<PolicySummary[]>([]);
  const [policy, setPolicy] = useState<PublicPolicy | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (authLoading) return;
    let active = true;
    setLoading(true); setError(""); setPolicy(null); setItems([]);
    if (!validScope) { setError("Policy page not found."); setLoading(false); return; }
    const request = kind
      ? policyRequest<PublicPolicy>(`/legal/${scope}/${encodeURIComponent(kind)}`).then(result => { if (active) setPolicy(result); })
      : policyRequest<{ items: PolicySummary[] }>(`/legal/${scope}`).then(result => { if (active) setItems(result.items); });
    void request.catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "Unable to load policies."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope, kind, validScope, authLoading, retry]);
  useEffect(() => {
    const previous = document.title;
    document.title = policy ? `${policy.content.title} | ${policy.content.business_name}` : "Public Policies | Tenali";
    return () => { document.title = previous; };
  }, [policy]);
  return <main className="ops-page policy-page">
    <nav className="policy-page-nav" aria-label="Policy navigation"><Link to="/">Home</Link><Link to={policyPath(scope)}>{scope === "tenant" ? "Store policies" : "Tenali platform policies"}</Link></nav>
    {authLoading || loading ? <p role="status">Loading public policies...</p> : error ? <section role="alert" className="ops-card"><h1>Policy unavailable</h1><p>{error}</p><button className="ops-link-btn" onClick={() => setRetry(value => value + 1)}>Retry</button></section> : policy ? <>
      <p className="policy-version">Published {new Date(policy.published_at).toLocaleDateString()} · Version {policy.published_revision} · {scope === "tenant" ? "Store policy" : "Tenali platform policy"}</p>
      <PolicyDocument content={policy.content} />
    </> : <section className="ops-card"><h1>{scope === "tenant" ? "Store policies" : "Tenali platform policies"}</h1><p>These are the business&apos;s published policies. Drafts are not public.</p>
      {items.length ? <ul>{items.map(item => <li key={item.kind}><Link to={policyPath(scope, item.kind)}>{item.title}</Link></li>)}</ul> : <p>No policies have been published yet. Contact the business before relying on any policy terms.</p>}
    </section>}
  </main>;
}

import { useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import type { DraftAction } from "../features/ai";
import { FloatingAlert } from "./Notifications";

export function PlatformAIActions({ companyId }: { companyId: string }) {
  const [items, setItems] = useState<DraftAction[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [highImpact, setHighImpact] = useState(false);
  const [module, setModule] = useState("");
  const path = "/ai/actions" + (companyId ? `?company_id=${encodeURIComponent(companyId)}` : "");
  useEffect(() => {
    let active = true;
    void accountRequest<{ items: DraftAction[] }>(path, undefined, "platform")
      .then(result => { if (active) setItems(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [path]);
  const update = async (item: DraftAction, tenant: boolean, review = false, execution = false) => {
    const enable = execution ? item.enabled : review || !item.enabled;
    const posting = execution ? !item.execution_enabled : false;
    if (!tenant && enable && !window.confirm(`${posting ? "Enable BUSINESS POSTING" : "Review and enable PRIVATE DRAFTS"} for ${item.key}?\n${item.description}\n\n${JSON.stringify(item.schema, null, 2)}\n\n${posting ? "This allows explicitly approved submissions to change business records." : "Draft preparation alone does not post records."} Tenant grant and current member permissions are required.`)) return;
    setBusy(true); setError("");
    try {
      await accountRequest(tenant ? `/ai/tenants/${companyId}/actions/${item.key}` : `/ai/actions/${item.key}`, {
        method: "PATCH", body: JSON.stringify(tenant
          ? { allowed: !item.tenant_allowed, expected_version: item.tenant_version }
          : { enabled: enable, execution_enabled: posting, approve_contract: enable, expected_version: item.version }),
      }, "platform");
      setItems((await accountRequest<{ items: DraftAction[] }>(path, undefined, "platform")).items);
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="settings-card"><h3>Operational actions</h3>
    <p className="social-caption">Review drafts first. Posting and workspace grants are separate controls; enabling drafts alone never changes business records.</p>
    <nav className="platform-ai-nav platform-ai-subnav" aria-label="Operational action groups">
      <button type="button" aria-current={!highImpact ? "page" : undefined} onClick={() => setHighImpact(false)}>Add & update</button>
      <button type="button" aria-current={highImpact ? "page" : undefined} onClick={() => setHighImpact(true)}>High impact</button>
    </nav>
    <label>Module<select value={module} onChange={event => setModule(event.target.value)}>
      <option value="">All modules</option>{[...new Set(items.map(item => item.module_path?.split("/")[1]).filter(Boolean))].sort().map(path =>
        <option key={path} value={path}>{path}</option>)}</select></label>
    {highImpact ? <p className="social-caption">High-impact operations require unrestricted owner/admin access and exact typed confirmation. Administrative settings and reset-all are excluded.</p> : null}
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    <div className="platform-ai-tool-list">{items.filter(item => Boolean(item.high_impact) === highImpact &&
      (!module || item.module_path?.split("/")[1] === module)).map(item => <details key={item.key} className="platform-ai-tool">
      <summary><span className="platform-ai-chevron" aria-hidden="true">&gt;</span><strong>{item.key.replace(/_/g, " ")}</strong><span>{!item.compatible && item.enabled ? "Review required" : item.execution_enabled ? "Posting on" : item.enabled ? "Drafts only" : "Off"}{companyId ? ` · Workspace ${item.tenant_allowed ? "allowed" : "blocked"}` : ""}</span></summary>
      <div className="platform-ai-tool-body"><p>{item.description}</p>
      <p>Platform: {item.enabled ? "enabled" : "disabled"} · Contract: {item.compatible ? "reviewed" : "review required"}</p>
      <div className="shop-actions"><button type="button" className="btn light" disabled={busy} onClick={() => void update(item, false)}>
        {item.enabled ? "Disable drafts" : "Review & enable drafts"}</button>
      {item.enabled && !item.compatible ? <button type="button" className="btn light" disabled={busy} onClick={() => void update(item, false, true)}>Review updated contract</button> : null}
      <button type="button" className="btn light" disabled={busy || !item.enabled || !item.compatible} onClick={() => void update(item, false, false, true)}>
        {item.execution_enabled ? "Disable posting" : "Enable approved posting"}</button></div>
      {companyId ? <label className="ops-toggle"><input type="checkbox" checked={item.tenant_allowed}
        disabled={busy || (!item.tenant_allowed && (!item.enabled || !item.compatible))}
        onChange={() => void update(item, true)} />Allow this draft action for the selected tenant</label> : null}
      </div>
    </details>)}</div>
    {!items.length && !error ? <p>Loading draft controls...</p> : null}
  </section>;
}

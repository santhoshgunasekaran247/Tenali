import { useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { FloatingAlert } from "./Notifications";

type Capability = {
  key: string; description: string; module_path: string | null; safety: "read";
  enabled: boolean; compatible: boolean; reason: string | null; version: number;
  tenant_allowed: boolean; tenant_version: number;
};

export function PlatformAICapabilities({ companyId }: { companyId: string }) {
  const [items, setItems] = useState<Capability[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const path = "/ai/capabilities" + (companyId ? `?company_id=${encodeURIComponent(companyId)}` : "");
  useEffect(() => {
    let active = true;
    void accountRequest<{ items: Capability[] }>(path, undefined, "platform")
      .then(result => { if (active) setItems(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [path]);
  const update = async (item: Capability, tenant: boolean) => {
    const approve = !tenant && !item.enabled;
    if (approve && !window.confirm(`Review and enable ${item.key}?\n${item.description}\nRead-only, module/store permissions enforced. Tenant permission is also required. No financial writes.`)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await accountRequest(tenant ? `/ai/tenants/${companyId}/capabilities/${item.key}` : `/ai/capabilities/${item.key}`, {
        method: "PATCH",
        body: JSON.stringify(tenant
          ? { allowed: !item.tenant_allowed, expected_version: item.tenant_version }
          : { enabled: approve, approve_contract: approve, expected_version: item.version }),
      }, "platform");
      setItems((await accountRequest<{ items: Capability[] }>(path, undefined, "platform")).items);
      setMessage("Read capability policy saved. Tenant AI opt-in and member permissions still apply.");
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="settings-card"><h3>Business lookups <span className="platform-ai-count">{items.filter(item => item.enabled && item.compatible).length} / {items.length} enabled</span></h3>
    <p className="social-caption">Read-only access; no business writes. Expand a lookup to review its contract and permissions.</p>
    <details className="platform-ai-help"><summary>How lookup permissions work</summary>
      <p>Changed contracts require review again. New workspaces have no lookup grants by default.
      Financial results are bounded records, not complete reports. Accounts, transactions and borrowing balances require
      unrestricted store access; invoice-linked receivables and refunds respect store restrictions.</p>
    </details>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {!items.length && !error ? <p>Loading read capabilities...</p> : null}
    <div className="platform-ai-tool-list">{items.map(item => <details key={item.key} className="platform-ai-tool">
      <summary><span className="platform-ai-chevron" aria-hidden="true">&gt;</span><strong>{item.key.replace(/_/g, " ")}</strong><span>{!item.compatible ? "Review required" : item.enabled ? "Enabled" : "Off"}{companyId ? ` · Workspace ${item.tenant_allowed ? "allowed" : "blocked"}` : ""}</span></summary>
      <div className="platform-ai-tool-body"><p>{item.description}</p>
      <p>Permission: {item.module_path} · Contract: {item.compatible ? "reviewed" : item.reason} · Platform: {item.enabled ? "enabled" : "disabled"}</p>
      <button type="button" className="btn light" disabled={busy} onClick={() => void update(item, false)}>
        {item.enabled ? "Disable lookup" : "Review & enable lookup"}
      </button>
      {companyId ? <label className="ops-toggle"><input type="checkbox" checked={item.tenant_allowed}
        disabled={busy || (!item.tenant_allowed && (!item.enabled || !item.compatible))}
        onChange={() => void update(item, true)} />Allow this lookup for the selected tenant</label> : null}
      </div>
    </details>)}</div>
  </section>;
}

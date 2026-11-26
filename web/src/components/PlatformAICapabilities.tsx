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
  const [module, setModule] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const path = "/ai/capabilities" + (companyId ? `?company_id=${encodeURIComponent(companyId)}` : "");
  useEffect(() => {
    let active = true;
    setSelected([]);
    void accountRequest<{ items: Capability[] }>(path, undefined, "platform")
      .then(result => { if (active) setItems(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [path]);
  const update = async (item: Capability, tenant: boolean, review = false) => {
    const approve = !tenant && (review || !item.enabled);
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
  const visible = items.filter(item => !module || item.module_path?.split("/")[1] === module);
  const chosen = visible.filter(item => selected.includes(item.key));
  const reviewSelected = async () => {
    if (!chosen.length || !window.confirm(`Review and enable ${chosen.length} selected lookups?\n\n${chosen.map(item =>
      `${item.key}: ${item.description}\nPermission: ${item.module_path}`).join("\n\n")}\n\nRead-only; no financial writes. Workspace grants and member permissions remain unchanged.`)) return;
    setBusy(true); setError(""); setMessage("");
    let saved = 0;
    try {
      for (const item of chosen) {
        await accountRequest(`/ai/capabilities/${item.key}`, { method: "PATCH", body: JSON.stringify({
          enabled: true, approve_contract: true, expected_version: item.version,
        }) }, "platform");
        saved++;
      }
      setMessage(`${saved} lookup contracts reviewed and enabled. Workspace grants remain unchanged.`);
    } catch (failure) {
      setError(`${saved} of ${chosen.length} lookups updated. Stopped at ${chosen[saved].key}: ${String(failure)}. Refresh before retrying; completed updates remain saved.`);
    } finally {
      setSelected(chosen.slice(saved).map(item => item.key));
      try { setItems((await accountRequest<{ items: Capability[] }>(path, undefined, "platform")).items); }
      catch (failure) { setItems([]); setError(previous => `${previous} Unable to refresh policies: ${String(failure)}. Reload this page before continuing.`.trim()); }
      setBusy(false);
    }
  };
  return <section className="settings-card"><h3>Business lookups <span className="platform-ai-count">{items.filter(item => item.enabled && item.compatible).length} / {items.length} enabled</span></h3>
    <p className="social-caption">Read-only access; no business writes. Expand a lookup to review its contract and permissions.</p>
    <details className="platform-ai-help"><summary>How lookup permissions work</summary>
      <p>Changed contracts require review again. New workspaces have no lookup grants by default.
      Financial results are bounded records, not complete reports. Accounts, transactions and borrowing balances require
      unrestricted store access; invoice-linked receivables and refunds respect store restrictions.</p>
    </details>
    <label>Module<select value={module} disabled={busy} onChange={event => { setModule(event.target.value); setSelected([]); }}>
      <option value="">All modules</option>{[...new Set(items.map(item => item.module_path?.split("/")[1]).filter(Boolean))].sort().map(path =>
        <option key={path} value={path}>{path}</option>)}</select></label>
    <div className="shop-actions">
      <label><input type="checkbox" disabled={busy || !visible.length}
        checked={visible.length > 0 && chosen.length === visible.length}
        onChange={event => setSelected(event.target.checked ? visible.map(item => item.key) : [])} />Select all visible lookups</label>
      <span>{chosen.length} selected</span>
      <button type="button" className="btn light" disabled={busy || !chosen.length}
        onClick={() => void reviewSelected()}>Review &amp; enable selected lookups</button>
    </div>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {!items.length && !error ? <p>Loading read capabilities...</p> : null}
    <div className="platform-ai-tool-list">{visible.map(item => <details key={item.key} className="platform-ai-tool">
      <summary><input type="checkbox" aria-label={`Select lookup ${item.key}`} disabled={busy} checked={selected.includes(item.key)}
        onClick={event => event.stopPropagation()} onChange={event => setSelected(previous => event.target.checked
          ? [...previous, item.key] : previous.filter(key => key !== item.key))} /><span className="platform-ai-chevron" aria-hidden="true">&gt;</span><strong>{item.key.replace(/_/g, " ")}</strong><span>{!item.compatible ? "Review required" : item.enabled ? "Enabled" : "Off"}{companyId ? ` · Workspace ${item.tenant_allowed ? "allowed" : "blocked"}` : ""}</span></summary>
      <div className="platform-ai-tool-body"><p>{item.description}</p>
      <p>Permission: {item.module_path} · Contract: {item.compatible ? "reviewed" : item.reason} · Platform: {item.enabled ? "enabled" : "disabled"}</p>
      <button type="button" className="btn light" disabled={busy} onClick={() => void update(item, false)}>
        {item.enabled ? "Disable lookup" : "Review & enable lookup"}
      </button>
      {item.enabled && !item.compatible ? <button type="button" className="btn light" disabled={busy}
        onClick={() => void update(item, false, true)}>Review updated contract</button> : null}
      {companyId ? <label className="ops-toggle"><input type="checkbox" checked={item.tenant_allowed}
        disabled={busy || (!item.tenant_allowed && (!item.enabled || !item.compatible))}
        onChange={() => void update(item, true)} />Allow this lookup for the selected tenant</label> : null}
      </div>
    </details>)}</div>
  </section>;
}

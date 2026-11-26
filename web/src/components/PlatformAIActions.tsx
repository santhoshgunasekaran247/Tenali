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
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const path = "/ai/actions" + (companyId ? `?company_id=${encodeURIComponent(companyId)}` : "");
  useEffect(() => {
    let active = true;
    setSelected([]);
    void accountRequest<{ items: DraftAction[] }>(path, undefined, "platform")
      .then(result => { if (active) setItems(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [path]);
  const update = async (item: DraftAction, tenant: boolean, review = false, execution = false) => {
    const enable = execution ? item.enabled : review || !item.enabled;
    const posting = execution ? !item.execution_enabled : false;
    if (!tenant && enable && !window.confirm(`${posting ? "Enable BUSINESS POSTING" : "Review and enable PRIVATE DRAFTS"} for ${item.key}?\n${item.description}\n\n${JSON.stringify(item.schema, null, 2)}\n\n${posting ? "This allows explicitly approved submissions to change business records." : "Draft preparation alone does not post records."} Tenant grant and current member permissions are required.`)) return;
    setBusy(true); setError(""); setMessage("");
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
  const visible = items.filter(item => Boolean(item.high_impact) === highImpact &&
    (!module || item.module_path?.split("/")[1] === module));
  const chosen = visible.filter(item => selected.includes(item.key));
  const postingReady = chosen.length > 0 && chosen.every(item => item.enabled && item.compatible);
  const updateSelected = async (posting: boolean) => {
    if (!chosen.length || (posting && !postingReady)) return;
    if (!window.confirm(`${posting ? "Enable BUSINESS POSTING" : "Review and enable PRIVATE DRAFTS"} for ${chosen.length} selected actions?\n\n${chosen.map(item =>
      `${item.key}: ${item.description}\n${JSON.stringify(item.schema, null, 2)}`).join("\n\n")}\n\n${posting
      ? "Explicitly approved submissions can change business records."
      : "This reviews the contracts and enables drafts. Posting will be OFF for these actions; enable it separately after review."} Workspace grants and member permissions remain unchanged.`)) return;
    setBusy(true); setError(""); setMessage("");
    let saved = 0;
    try {
      for (const item of chosen) {
        await accountRequest(`/ai/actions/${item.key}`, { method: "PATCH", body: JSON.stringify({
          enabled: true, execution_enabled: posting, approve_contract: !posting, expected_version: item.version,
        }) }, "platform");
        saved++;
      }
      setMessage(posting ? `${saved} actions enabled for approved posting. Workspace grants remain unchanged.`
        : `${saved} action contracts reviewed and drafts enabled. Selected actions are retained so you can enable posting separately.`);
    } catch (failure) {
      setSelected(chosen.slice(saved).map(item => item.key));
      setError(`${saved} of ${chosen.length} actions updated. Stopped at ${chosen[saved].key}: ${String(failure)}. Refresh before retrying; completed updates remain saved.`);
    } finally {
      try { setItems((await accountRequest<{ items: DraftAction[] }>(path, undefined, "platform")).items); }
      catch (failure) { setItems([]); setError(previous => `${previous} Unable to refresh policies: ${String(failure)}. Reload this page before continuing.`.trim()); }
      setBusy(false);
    }
  };
  return <section className="settings-card"><h3>Operational actions</h3>
    <p className="social-caption">Review drafts first. Posting and workspace grants are separate controls; enabling drafts alone never changes business records.</p>
    <nav className="platform-ai-nav platform-ai-subnav" aria-label="Operational action groups">
      <button type="button" disabled={busy} aria-current={!highImpact ? "page" : undefined} onClick={() => { setHighImpact(false); setSelected([]); }}>Add & update</button>
      <button type="button" disabled={busy} aria-current={highImpact ? "page" : undefined} onClick={() => { setHighImpact(true); setSelected([]); }}>High impact</button>
    </nav>
    <label>Module<select value={module} disabled={busy} onChange={event => { setModule(event.target.value); setSelected([]); }}>
      <option value="">All modules</option>{[...new Set(items.map(item => item.module_path?.split("/")[1]).filter(Boolean))].sort().map(path =>
        <option key={path} value={path}>{path}</option>)}</select></label>
    <div className="shop-actions">
      <label><input type="checkbox" disabled={busy || !visible.length}
        checked={visible.length > 0 && chosen.length === visible.length}
        onChange={event => setSelected(event.target.checked ? visible.map(item => item.key) : [])} />Select all visible actions</label>
      <span>{chosen.length} selected</span>
      <button type="button" className="btn light" disabled={busy || !chosen.length}
        onClick={() => void updateSelected(false)}>Review &amp; enable selected drafts</button>
      <button type="button" className="btn light" disabled={busy || !postingReady}
        onClick={() => void updateSelected(true)}>Enable selected posting</button>
    </div>
    <p className="social-caption">Review selected contracts first, then enable posting separately. These bulk controls do not change workspace grants.</p>
    {highImpact ? <p className="social-caption">High-impact operations require unrestricted owner/admin access and exact typed confirmation. Administrative settings and reset-all are excluded.</p> : null}
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <div className="platform-ai-tool-list">{visible.map(item => <details key={item.key} className="platform-ai-tool">
      <summary><input type="checkbox" aria-label={`Select action ${item.key}`} disabled={busy} checked={selected.includes(item.key)}
        onClick={event => event.stopPropagation()} onChange={event => setSelected(previous => event.target.checked
          ? [...previous, item.key] : previous.filter(key => key !== item.key))} /><span className="platform-ai-chevron" aria-hidden="true">&gt;</span><strong>{item.key.replace(/_/g, " ")}</strong><span>{!item.compatible && item.enabled ? "Review required" : item.execution_enabled ? "Posting on" : item.enabled ? "Drafts only" : "Off"}{companyId ? ` · Workspace ${item.tenant_allowed ? "allowed" : "blocked"}` : ""}</span></summary>
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

import { FormEvent, useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { AI_LIMIT_FIELDS, type AIOverrides, type PlatformAIConfig, type PlatformWorkspace, type TenantLimits } from "../features/featureControls";
import { FloatingAlert } from "./Notifications";
import { PlatformWorkspaceFeatures } from "./PlatformWorkspaceFeatures";
import { PlatformAICapabilities } from "./PlatformAICapabilities";

export function PlatformAISettings() {
  const [form, setForm] = useState<PlatformAIConfig | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [workspaces, setWorkspaces] = useState<PlatformWorkspace[]>([]);
  const [offset, setOffset] = useState(0);
  const [companyId, setCompanyId] = useState("");
  const [limits, setLimits] = useState<TenantLimits | null>(null);
  const [overrides, setOverrides] = useState<AIOverrides | null>(null);
  const [usage, setUsage] = useState<Array<{ company_id: string; model: string; requests: number; tokens: string | number; cost: string | number; unconfirmed: number }>>([]);
  const [usageOffset, setUsageOffset] = useState(0);
  useEffect(() => {
    let active = true;
    void accountRequest<{ items: typeof usage }>(`/ai/usage?offset=${usageOffset}`, undefined, "platform")
      .then(result => { if (active) setUsage(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [usageOffset]);
  useEffect(() => {
    let active = true;
    void accountRequest<PlatformAIConfig>("/ai/settings", undefined, "platform")
      .then(result => { if (active) setForm(result); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    void accountRequest<{ items: PlatformWorkspace[] }>(`/workspaces?offset=${offset}`, undefined, "platform")
      .then(result => { if (active) setWorkspaces(result.items); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [offset]);
  useEffect(() => {
    setLimits(null); setOverrides(null);
    if (!companyId) return;
    let active = true;
    void accountRequest<TenantLimits>(`/ai/tenants/${companyId}`, undefined, "platform")
      .then(result => { if (active) { setLimits(result); setOverrides(result.overrides); } })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [companyId]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setBusy(true); setError(""); setMessage("");
    const { version, provider_configured, runtime_ready, model_ready, ...config } = form;
    try {
      const result = await accountRequest<PlatformAIConfig>("/ai/settings", { method: "PUT",
        body: JSON.stringify({ ...config, expected_version: version }) }, "platform");
      setForm(result); setMessage("AI platform policy saved. Chat additionally requires a server-approved model, configured pricing/key, tenant permission and opt-in.");
      if (companyId) {
        const updated = await accountRequest<TenantLimits>(`/ai/tenants/${companyId}`, undefined, "platform");
        setLimits(updated); setOverrides(updated.overrides);
      }
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const saveLimits = async (event: FormEvent) => {
    event.preventDefault();
    if (!limits || !overrides) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await accountRequest<TenantLimits>(`/ai/tenants/${companyId}`, { method: "PATCH",
        body: JSON.stringify({ ...overrides, expected_version: limits.version }) }, "platform");
      setLimits(result); setOverrides(result.overrides); setMessage("Tenant AI limits saved.");
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="platform-ai-settings">
    <div className="platform-section-title"><h2>Tenali AI</h2><p>Platform policy and limits for all tenants. New tools still require verified adapters.</p></div>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {!form ? <p role="status">{error ? "Unable to load AI configuration. Refresh to retry." : "Loading AI configuration..."}</p> : <>
      <PlatformAICapabilities key={companyId} companyId={companyId} />
      <section className="settings-card"><h3>Provider status</h3>
        <p>Server key: {form.provider_configured ? "configured" : "not configured"} · Assistant runtime: {form.runtime_ready ? "available" : "not deployed"}</p>
        <p>Model/pricing ready: {form.model_ready ? "yes" : "no"}</p>
        <p className="social-caption">Models must be independently approved for Responses structured output and listed in the server's OPENAI_ALLOWED_MODELS. Saving settings does not test connectivity. Keep credentials in the backend environment, never in this page.</p>
      </section>
      <form className="ops-form" onSubmit={save}><fieldset disabled={busy} className="settings-card">
        <legend>Platform defaults and ceilings</legend>
        <label className="ops-toggle"><input type="checkbox" checked={form.global_enabled} onChange={event => setForm({ ...form, global_enabled: event.target.checked })} />Allow AI platform-wide (availability policy)</label>
        <p className="social-caption">Each tenant also needs platform permission and its own opt-in. Turning this off preserves preferences; it does not undo business transactions.</p>
        <div className="ai-settings-grid">
          <label>Routine model<input required={form.global_enabled} maxLength={100} value={form.routine_model} onChange={event => setForm({ ...form, routine_model: event.target.value })} /></label>
          <label>Document model<input required={form.global_enabled} maxLength={100} value={form.document_model} onChange={event => setForm({ ...form, document_model: event.target.value })} /></label>
          <label>Routine model input price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.input_cost_per_million} onChange={event => setForm({ ...form, input_cost_per_million: event.target.value })} /></label>
          <label>Routine model output price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.output_cost_per_million} onChange={event => setForm({ ...form, output_cost_per_million: event.target.value })} /></label>
          {AI_LIMIT_FIELDS.map(([key, label, max]) => <label key={key}>{label}<input type="number" required min={1} max={max} step={1} value={form[key]}
            onChange={event => setForm({ ...form, [key]: Number(event.target.value) })} /></label>)}
          <label>Maximum output tokens<input type="number" required min={100} max={32000} step={1} value={form.max_output_tokens} onChange={event => setForm({ ...form, max_output_tokens: Number(event.target.value) })} /></label>
          <label>Provider timeout (seconds)<input type="number" required min={10} max={120} step={1} value={form.timeout_seconds} onChange={event => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label>
          <label>Planned chat retention (days)<input type="number" required min={1} max={3650} step={1} value={form.retention_days} onChange={event => setForm({ ...form, retention_days: Number(event.target.value) })} /></label>
          <label>Platform contact link<input maxLength={300} placeholder="https://support.example.com or mailto:support@example.com" value={form.support_url} onChange={event => setForm({ ...form, support_url: event.target.value })} /></label>
        </div>
        <p className="social-caption">Tenant overrides can only lower these ceilings. Update prices when changing models. Zero pricing blocks chat. Costs are conservative USD estimates, not customer charges. Chat limits include pending/unknown calls; retention scrubbing must be scheduled on the server.</p>
        <button className="btn" disabled={busy}>{busy ? "Saving..." : "Save platform AI settings"}</button>
      </fieldset></form>
    </>}
    <section className="settings-card"><h3>Tenant controls</h3>
      <label>Workspace<select disabled={busy} value={companyId} onChange={event => { setCompanyId(event.target.value); setError(""); setMessage(""); }}>
        <option value="">Choose a workspace</option>{workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.company_name} ({workspace.tenant_slug}){workspace.is_active ? "" : " - disabled"}</option>)}
      </select></label>
      <div className="shop-actions"><button type="button" disabled={busy || !offset} onClick={() => { setCompanyId(""); setOffset(Math.max(0, offset - 50)); }}>Previous tenants</button>
        <button type="button" disabled={busy || workspaces.length < 50} onClick={() => { setCompanyId(""); setOffset(offset + 50); }}>Next tenants</button></div>
      {companyId ? <PlatformWorkspaceFeatures key={`${companyId}:${form?.version}`} companyId={companyId} /> : null}
      {companyId && limits && overrides ? <form className="ops-form" onSubmit={saveLimits}><fieldset disabled={busy}>
        <legend>Tenant AI limits</legend><p className="social-caption">Leave blank to inherit. To reset, clear each override and save.</p>
        <div className="ai-settings-grid">{AI_LIMIT_FIELDS.map(([key, label, max]) => <label key={key}>{label}
          <input type="number" min={1} max={max} step={1} placeholder={`Inherited: ${limits.effective[key]}`} value={overrides[key] ?? ""}
            onChange={event => setOverrides({ ...overrides, [key]: event.target.value === "" ? null : Number(event.target.value) })} />
          <span className="social-caption">Effective: {limits.effective[key]}</span>
        </label>)}</div><button className="btn light" disabled={busy}>Save tenant limits</button>
      </fieldset></form> : null}
    </section>
    <section className="settings-card"><h3>Capabilities, usage and audit</h3>
      <p>Chat is available when enabled and configured. No business execution capabilities are active yet. Usage metadata is available through the platform AI usage API; private transcripts are not.</p>
      <p className="social-caption">Current UTC month. Includes conservative reservations for calls with unconfirmed usage.</p>
      {usage.length ? <div className="ops-table-wrap"><table><thead><tr><th>Tenant ID</th><th>Model</th><th>Requests</th><th>Tokens</th><th>Estimated USD</th><th>Unconfirmed</th></tr></thead><tbody>{usage.map(row =>
        <tr key={`${row.company_id}:${row.model}`}><td>{row.company_id}</td><td>{row.model}</td><td>{row.requests}</td><td>{row.tokens}</td><td>{Number(row.cost).toFixed(4)}</td><td>{row.unconfirmed}</td></tr>)}</tbody></table></div> : <p>No AI usage recorded on this page.</p>}
      <div className="shop-actions"><button type="button" disabled={!usageOffset} onClick={() => setUsageOffset(Math.max(0, usageOffset - 50))}>Previous usage</button>
        <button type="button" disabled={usage.length < 50} onClick={() => setUsageOffset(usageOffset + 50)}>Next usage</button></div>
      <p className="social-caption">Configuration and entitlement changes are recorded in the existing platform audit. Private user conversations will not be available to platform administrators by default.</p>
    </section>
  </section>;
}

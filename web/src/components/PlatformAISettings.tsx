import { FormEvent, useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { AI_LIMIT_FIELDS, type AIOverrides, type PlatformAIConfig, type PlatformWorkspace, type TenantLimits } from "../features/featureControls";
import { FloatingAlert } from "./Notifications";
import { PlatformWorkspaceFeatures } from "./PlatformWorkspaceFeatures";
import { PlatformAICapabilities } from "./PlatformAICapabilities";
import { PlatformAIActions } from "./PlatformAIActions";

export function PlatformAISettings() {
  const [section, setSection] = useState<"settings" | "tools" | "workspaces" | "usage">("settings");
  const [toolsView, setToolsView] = useState<"reads" | "actions">("reads");
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
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <nav className="platform-ai-nav" aria-label="AI administration">
      {(["settings", "tools", "workspaces", "usage"] as const).map(item => <button type="button" key={item}
        aria-current={section === item ? "page" : undefined} aria-controls={`platform-ai-${item}`}
        onClick={() => setSection(item)}>{item === "settings" ? "Settings" : item === "tools" ? "Tools & permissions" : item === "workspaces" ? "Workspaces" : "Usage"}</button>)}
    </nav>
    {!form ? <p role="status">{error ? "Unable to load AI configuration. Refresh to retry." : "Loading AI configuration..."}</p> : <>
      <div className="platform-ai-status" aria-label="AI configuration status">
        <span>Platform AI <strong>{form.global_enabled ? "Allowed" : "Off"}</strong></span>
        <span>Server key <strong>{form.provider_configured ? "Configured" : "Missing"}</strong></span>
        <span>Runtime <strong>{form.runtime_ready ? "Available" : "Not deployed"}</strong></span>
        <span>Model & pricing <strong>{form.model_ready ? "Ready" : "Needs setup"}</strong></span>
      </div>
      <section id="platform-ai-settings" hidden={section !== "settings"} className="platform-ai-panel">
      <div className="platform-section-title"><h2>Settings</h2><p>Choose models and set shared spending ceilings. Changes apply only after saving.</p></div>
      <form className="ops-form" onSubmit={save} onInvalid={event => {
        if (event.target instanceof HTMLElement) {
          const disclosure = event.target.closest("details");
          if (disclosure) disclosure.open = true;
        }
      }}><fieldset disabled={busy} className="platform-ai-fieldset">
      <section className="settings-card">
        <h3>Availability</h3>
        <label className="ops-toggle"><input type="checkbox" checked={form.global_enabled} onChange={event => setForm({ ...form, global_enabled: event.target.checked })} />Allow AI platform-wide (availability policy)</label>
        <p className="social-caption">Workspaces still need permission and their own opt-in. Turning AI off preserves preferences and does not undo transactions.</p>
      </section>
      <section className="settings-card"><h3>Chat model & pricing</h3>
        <div className="ai-settings-grid">
          <label>Routine model<input required={form.global_enabled} maxLength={100} value={form.routine_model} onChange={event => setForm({ ...form, routine_model: event.target.value })} /></label>
          <label>Routine model input price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.input_cost_per_million} onChange={event => setForm({ ...form, input_cost_per_million: event.target.value })} /></label>
          <label>Routine model output price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.output_cost_per_million} onChange={event => setForm({ ...form, output_cost_per_million: event.target.value })} /></label>
        </div>
        <p className="social-caption">Use an approved model ID from OPENAI_ALLOWED_MODELS. Update prices when changing models; zero pricing blocks chat. Credentials stay in the backend. Saving does not test connectivity.</p>
      </section>
      <details className="settings-card platform-ai-disclosure">
        <summary>Documents & images <span>{form.document_inputs_enabled ? "Enabled" : "Off"}</span></summary>
        <p className="social-caption">Private files use a separately approved model and pricing. Upload alone makes no provider call; Send processes selected files.</p>
        <label className="ops-toggle"><input type="checkbox" checked={form.document_inputs_enabled} onChange={event => setForm({ ...form, document_inputs_enabled: event.target.checked })} />Allow private text/document/image inputs</label>
        <div className="ai-settings-grid">
          <label>Document model<input required={form.global_enabled} maxLength={100} value={form.document_model} onChange={event => setForm({ ...form, document_model: event.target.value })} /></label>
          <label>Document input price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.document_input_cost_per_million} onChange={event => setForm({ ...form, document_input_cost_per_million: event.target.value })} /></label>
          <label>Document output price (USD / million tokens)<input type="number" min={0} max={1000} step="0.000001" required value={form.document_output_cost_per_million} onChange={event => setForm({ ...form, document_output_cost_per_million: event.target.value })} /></label>
        </div>
      </details>
      <details className="settings-card platform-ai-disclosure">
        <summary>Voice input <span>{form.voice_inputs_enabled ? "Enabled" : "Off"}</span></summary>
        <p className="social-caption">Microphone recordings become editable English/Tamil text. Voice uses duration pricing and shares request/spending ceilings; it never sends chat or approves operations automatically.</p>
        <label className="ops-toggle"><input type="checkbox" checked={form.voice_inputs_enabled ?? false}
          onChange={event => setForm({ ...form, voice_inputs_enabled: event.target.checked })} />Allow microphone transcription</label>
        <div className="ai-settings-grid">
          <label>Transcription model<input maxLength={100} required={form.voice_inputs_enabled} placeholder="gpt-transcribe"
            value={form.transcription_model ?? ""} onChange={event => setForm({ ...form, transcription_model: event.target.value })} /></label>
          <label>Voice price (USD / minute)<input type="number" min={form.voice_inputs_enabled ? 0.000001 : 0} max={10} step="0.000001" required
            value={form.transcription_cost_per_minute ?? 0} onChange={event => setForm({ ...form, transcription_cost_per_minute: event.target.value })} /></label>
        </div>
        <p className="social-caption">Use duration-billed gpt-transcribe and add its exact ID to backend OPENAI_ALLOWED_MODELS. Configure its current per-minute price; chat/document token prices are not reused.</p>
      </details>
      <section className="settings-card"><h3>Usage & spending ceilings</h3>
        <div className="ai-settings-grid">
          {AI_LIMIT_FIELDS.map(([key, label, max]) => <label key={key}>{label}<input type="number" required min={1} max={max} step={1} value={form[key]}
            onChange={event => setForm({ ...form, [key]: Number(event.target.value) })} /></label>)}
        </div>
        <p className="social-caption">Workspace overrides can only lower these ceilings. Pending/unknown calls count toward limits. USD costs are conservative estimates, not customer charges.</p>
      </section>
      <details className="settings-card platform-ai-disclosure"><summary>Advanced settings <span>Response, retention & support</span></summary>
        <div className="ai-settings-grid">
          <label>Maximum output tokens<input type="number" required min={100} max={32000} step={1} value={form.max_output_tokens} onChange={event => setForm({ ...form, max_output_tokens: Number(event.target.value) })} /></label>
          <label>Provider timeout (seconds)<input type="number" required min={10} max={120} step={1} value={form.timeout_seconds} onChange={event => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label>
          <label>Planned chat retention (days)<input type="number" required min={1} max={3650} step={1} value={form.retention_days} onChange={event => setForm({ ...form, retention_days: Number(event.target.value) })} /></label>
          <label>Platform contact link<input maxLength={300} placeholder="https://support.example.com or mailto:support@example.com" value={form.support_url} onChange={event => setForm({ ...form, support_url: event.target.value })} /></label>
        </div>
        <p className="social-caption">Retention scrubbing must be scheduled on the server.</p>
      </details>
      <div className="settings-save-bar"><p>Save all platform settings together.</p><button className="btn" disabled={busy}>{busy ? "Saving..." : "Save platform AI settings"}</button></div>
      </fieldset></form>
      </section>
    </>}
    <section hidden={section !== "tools" && section !== "workspaces"} className="settings-card platform-ai-scope">
      <label>Workspace<select disabled={busy} value={companyId} onChange={event => { setCompanyId(event.target.value); setError(""); setMessage(""); }}>
        <option value="">Platform defaults (no workspace selected)</option>{workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.company_name} ({workspace.tenant_slug}){workspace.is_active ? "" : " - disabled"}</option>)}
      </select></label>
      <p className="social-caption">Select a workspace to manage its access, limits and individual tool grants. Platform tool switches always apply to every workspace.</p>
      <div className="shop-actions"><button type="button" disabled={busy || !offset} onClick={() => { setCompanyId(""); setOffset(Math.max(0, offset - 50)); }}>Previous tenants</button>
        <button type="button" disabled={busy || workspaces.length < 50} onClick={() => { setCompanyId(""); setOffset(offset + 50); }}>Next tenants</button></div>
    </section>
    {form ? <section id="platform-ai-tools" hidden={section !== "tools"} className="platform-ai-panel">
      <div className="platform-section-title"><h2>Tools & permissions</h2><p>{companyId ? `Workspace grants: ${workspaces.find(workspace => workspace.id === companyId)?.company_name ?? companyId}.` : "Platform defaults. Select a workspace above to grant individual tools."} Draft preparation, posting and workspace permission are separate.</p></div>
      <nav className="platform-ai-nav platform-ai-subnav" aria-label="AI tool categories">
        <button type="button" aria-current={toolsView === "reads" ? "page" : undefined} onClick={() => setToolsView("reads")}>Business lookups</button>
        <button type="button" aria-current={toolsView === "actions" ? "page" : undefined} onClick={() => setToolsView("actions")}>Operational actions</button>
      </nav>
      <div hidden={toolsView !== "reads"}><PlatformAICapabilities key={companyId} companyId={companyId} /></div>
      <div hidden={toolsView !== "actions"}><PlatformAIActions key={companyId} companyId={companyId} /></div>
    </section> : null}
    <section id="platform-ai-workspaces" hidden={section !== "workspaces"} className="platform-ai-panel">
      <div className="platform-section-title"><h2>Workspace access & limits</h2><p>Allow workspace access here, then grant individual tools in Tools & permissions.</p></div>
      {!companyId ? <p>Select a workspace above to manage its AI access and limits.</p> : <section className="settings-card">
      <PlatformWorkspaceFeatures key={`${companyId}:${form?.version}`} companyId={companyId} />
      {companyId && limits && overrides ? <form className="ops-form" onSubmit={saveLimits}><fieldset disabled={busy}>
        <legend>Tenant AI limits</legend><p className="social-caption">Leave blank to inherit. To reset, clear each override and save.</p>
        <div className="ai-settings-grid">{AI_LIMIT_FIELDS.map(([key, label, max]) => <label key={key}>{label}
          <input type="number" min={1} max={max} step={1} placeholder={`Inherited: ${limits.effective[key]}`} value={overrides[key] ?? ""}
            onChange={event => setOverrides({ ...overrides, [key]: event.target.value === "" ? null : Number(event.target.value) })} />
          <span className="social-caption">Effective: {limits.effective[key]}</span>
        </label>)}</div><button className="btn light" disabled={busy}>Save tenant limits</button>
      </fieldset></form> : <p role="status">{error ? "Unable to load workspace limits." : "Loading workspace limits..."}</p>}
      </section>}
    </section>
    <section id="platform-ai-usage" hidden={section !== "usage"} className="settings-card">
      <h2>Usage</h2>
      <p className="social-caption">Current UTC month. Includes conservative reservations for calls with unconfirmed usage.</p>
      {usage.length ? <div className="ops-table-wrap"><table><thead><tr><th>Tenant ID</th><th>Model</th><th>Requests</th><th>Tokens</th><th>Estimated USD</th><th>Unconfirmed</th></tr></thead><tbody>{usage.map(row =>
        <tr key={`${row.company_id}:${row.model}`}><td>{row.company_id}</td><td>{row.model}</td><td>{row.requests}</td><td>{row.tokens}</td><td>{Number(row.cost).toFixed(4)}</td><td>{row.unconfirmed}</td></tr>)}</tbody></table></div> : <p>No AI usage recorded on this page.</p>}
      <div className="shop-actions"><button type="button" disabled={!usageOffset} onClick={() => setUsageOffset(Math.max(0, usageOffset - 50))}>Previous usage</button>
        <button type="button" disabled={usage.length < 50} onClick={() => setUsageOffset(usageOffset + 50)}>Next usage</button></div>
      <p className="social-caption">Configuration and entitlement changes are recorded in the existing platform audit. Private user conversations will not be available to platform administrators by default.</p>
    </section>
  </section>;
}

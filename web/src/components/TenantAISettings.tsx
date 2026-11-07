import { useEffect, useState } from "react";
import { tenantFetch } from "../features/tenantTransport";
import { featureExplanation, platformLocked } from "../features/featureControls";
import type { CompanyFeatures } from "../types";
import { FloatingAlert } from "./Notifications";

async function settingsRequest(options?: RequestInit): Promise<CompanyFeatures> {
  const response = await tenantFetch("/api/ai/settings", { ...options, headers: {
    "Content-Type": "application/json", ...options?.headers,
  } });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Unable to save AI preferences.");
  return body;
}

export function TenantAISettings() {
  const [features, setFeatures] = useState<CompanyFeatures | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    void settingsRequest().then(result => {
      if (active) { setFeatures(result); setEnabled(result.ai.tenant_enabled); }
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, []);
  const save = async () => {
    if (!features) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await settingsRequest({ method: "PATCH", body: JSON.stringify({
        tenant_enabled: enabled, expected_version: features.ai_settings_version,
      }) });
      setFeatures(result); setEnabled(result.ai.tenant_enabled); setMessage("AI preference saved. " + featureExplanation(result.ai));
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  const locked = !features || platformLocked(features.ai);
  return <section className="tenant-ai-settings" aria-label="Tenali AI preference">
    <h3>Tenali AI</h3>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {!features ? <p>{error ? "AI settings unavailable. Refresh to retry." : "Loading AI settings..."}</p> : <>
      <label className="ops-toggle"><input type="checkbox" checked={!locked && enabled} disabled={busy || locked} aria-describedby="ai-policy-note"
        onChange={event => { setEnabled(event.target.checked); setMessage(""); }} />Enable Tenali AI for this workspace</label>
      <p className="ops-copy-note" id="ai-policy-note">{featureExplanation(features.ai)}</p>
      {locked ? <p><span className="feature-contact-tag">Contact platform</span>{features.support_url ? <> <a href={features.support_url}>Contact platform administrator</a></> : null}</p> : null}
      <p className="social-caption">Saved separately from company details. Chat may send your messages and basic company context to OpenAI; no business transactions are executed. No provider requests are made by this settings control.</p>
      <button type="button" className="btn light" disabled={busy || locked || enabled === features.ai.tenant_enabled} onClick={() => void save()}>{busy ? "Saving..." : "Save AI preference"}</button>
    </>}
  </section>;
}

import { useEffect, useState } from "react";
import { accountRequest } from "../features/shop";
import { featureExplanation } from "../features/featureControls";
import type { CompanyFeatures } from "../types";
import { FloatingAlert } from "./Notifications";

export function PlatformWorkspaceFeatures({ companyId }: { companyId: string }) {
  const [features, setFeatures] = useState<CompanyFeatures | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void accountRequest<CompanyFeatures>(`/workspaces/${companyId}/features`, undefined, "platform")
      .then(result => { if (active) setFeatures(result); })
      .catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [companyId]);
  const change = async (key: "ai" | "storefront") => {
    if (!features) return;
    const status = features[key];
    if (!window.confirm(`${status.platform_allowed ? "Disable" : "Allow"} ${key === "ai" ? "AI" : "storefront"} for this workspace? ${status.platform_allowed ? "Operations access remains available." : "The tenant's saved preference will be restored; this does not force it on."}`)) return;
    setBusy(true); setError("");
    try {
      setFeatures(await accountRequest<CompanyFeatures>(`/workspaces/${companyId}/features`, {
        method: "PATCH", body: JSON.stringify({ feature_key: key, platform_allowed: !status.platform_allowed, expected_version: status.version }),
      }, "platform"));
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="workspace-feature-controls" aria-label="Workspace feature availability">
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {!features ? <p>{error ? "Unable to load features. Close and reopen to retry." : "Loading features..."}</p> : <>
      {(["ai", "storefront"] as const).map(key => <div className="workspace-feature-row" key={key}>
        <div><strong>{key === "ai" ? "Tenali AI" : "Storefront"}</strong>
          <p className="social-caption">Platform: {features[key].platform_allowed ? "allowed" : "blocked"} · Tenant preference: {features[key].tenant_enabled ? "on" : "off"} · Effective: {features[key].effective_enabled ? "on" : "off"}</p>
          <p className="social-caption">{featureExplanation(features[key])}</p>
        </div>
        <button type="button" className="btn light" disabled={busy} onClick={() => void change(key)}>
          {features[key].platform_allowed ? "Disable" : "Allow"} {key === "ai" ? "AI" : "storefront"}
        </button>
      </div>)}
      <p className="social-caption">Blocking a feature preserves tenant preferences. Existing order tracking and reconciliation continue; disabling AI does not undo transactions.</p>
    </>}
  </section>;
}

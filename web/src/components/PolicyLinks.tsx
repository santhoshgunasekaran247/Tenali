import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";
import { PLATFORM_POLICY_KINDS, POLICY_TITLES, TENANT_POLICY_KINDS, policyPath, type PolicyScope } from "../features/policies";
import { tenantBase } from "../features/tenantTransport";

export function PolicyLinks() {
  const { storefront } = useAuth();
  const scope: PolicyScope = storefront || tenantBase() ? "tenant" : "platform";
  const kinds = scope === "tenant" ? TENANT_POLICY_KINDS : PLATFORM_POLICY_KINDS;
  return <nav className="policy-links" aria-label="Public policies">
    <strong>{scope === "tenant" ? "Store policies" : "Tenali platform policies"}</strong>
    {kinds.map(kind => <Link key={kind} to={policyPath(scope, kind)}>{POLICY_TITLES[kind]}</Link>)}
    {scope === "tenant" ? <Link to={policyPath("platform")}>Tenali platform policies</Link> : null}
  </nav>;
}

export function PolicyNotice({ scope }: { scope: PolicyScope }) {
  return <p className="policy-notice">Read the {scope === "tenant" ? "store's" : "Tenali platform's"}{" "}
    <Link to={policyPath(scope, "privacy")}>privacy policy (including sign-in data)</Link> and{" "}
    <Link to={policyPath(scope, "terms")}>terms of service</Link>.{" "}
    <Link to={policyPath(scope, "data-deletion")}>Account/data deletion instructions</Link>.
    {scope === "tenant" ? <> The <Link to={policyPath("platform", "privacy")}>platform privacy policy</Link> also explains Tenali&apos;s processing.</> : null}
  </p>;
}

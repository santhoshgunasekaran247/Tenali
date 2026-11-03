import { PolicyEditor } from "../components/PolicyEditor";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { useAuth } from "../features/auth";

export function TenantPoliciesPage() {
  const { user } = useAuth();
  return <main className="ops-page"><PortalHomeLink /><h1>Store Policies</h1>
    {user && ["owner", "admin"].includes(user.role) ? <PolicyEditor key={user.company_id} scope="tenant" /> : <p className="ops-error" role="alert">Only owners and administrators can manage store policies.</p>}
  </main>;
}

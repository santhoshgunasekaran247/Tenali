import { Link } from "react-router-dom";
import { OnlineCustomerLinks } from "../components/OnlineCustomerLinks";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { useAuth } from "../features/auth";

export function OnlineCustomersPage() {
  const { user } = useAuth();
  const permitted = !!user && ["owner", "admin"].includes(user.role);
  return <main className="ops-page">
    <header className="ops-hero">
      <PortalHomeLink />
      <p className="eyebrow">OPERATIONS</p>
      <h1>Online customers</h1>
      <p>Manage storefront customer accounts separately from your billing customers and vendors.</p>
    </header>
    <p><Link className="ops-inline-link" to="/portal/parties">Go to customers and vendors</Link></p>
    {permitted ? <OnlineCustomerLinks key={user.company_id} /> :
      <p className="ops-error" role="alert">Only owners and administrators can manage online customer accounts.</p>}
  </main>;
}

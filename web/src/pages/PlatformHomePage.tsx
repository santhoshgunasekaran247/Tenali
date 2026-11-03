import { Link } from "react-router-dom";
import { policyPath } from "../features/policies";

export function PlatformHomePage() {
  return <main className="ops-page policy-page">
    <header className="ops-hero"><p className="eyebrow">SRU GLOBAL</p><h1>Tenali Business Platform</h1>
      <p>Business workspaces and independent online storefronts, with inventory, billing, accounts and order management in one place.</p>
    </header>
    <section className="ops-card"><h2>For business owners and their customers</h2>
      <p>Owners manage their company, catalogue, team and business records in a dedicated workspace. Shoppers browse a seller&apos;s storefront and use a separate store account for orders.</p>
      <p>Social sign-in uses enabled identity providers through Supabase. Stores may offer Razorpay payments and Shiprocket-assisted delivery using their own configured provider accounts. Each seller is responsible for its products, prices, fulfilment and commercial policies.</p>
      <div className="shop-actions"><Link className="btn" to="/login">Sign in to a workspace</Link><Link className="btn light" to="/register">Create a workspace</Link></div>
    </section>
    <section className="ops-card"><h2>Transparency and support</h2>
      <p>Tenali is operated by Sru Global. Read our <Link to={policyPath("platform", "privacy")}>privacy policy</Link>, <Link to={policyPath("platform", "terms")}>terms of service</Link> and <Link to={policyPath("platform", "data-deletion")}>account/data-deletion instructions</Link>.</p>
      <p><Link to={policyPath("platform", "contact")}>Contact and business information</Link>. For store orders, use the seller&apos;s contact and policies on that storefront.</p>
    </section>
  </main>;
}

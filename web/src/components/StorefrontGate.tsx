import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";

export function StorefrontGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  if (auth.loading) return <main className="loading">Loading...</main>;
  const store = auth.storefront;
  if (!store || store.storefront_enabled !== false) return <>{children}</>;
  const owner = auth.user?.company_id === store.id;
  return (
    <main className="ops-page storefront-closed">
      <section className="ops-card" role="status">
        <h1>{store.nickname || store.company_name}</h1>
        <p>Our online store is currently unavailable. Please check back later.</p>
        {store.phone || store.email ? (
          <p>
            Contact us
            {store.phone ? <> at <a href={`tel:${store.phone}`}>{store.phone}</a></> : null}
            {store.phone && store.email ? " or" : null}
            {store.email ? <> at <a href={`mailto:${store.email}`}>{store.email}</a></> : null}
            .
          </p>
        ) : null}
        <p><Link to="/account">View an existing order</Link></p>
        {owner ? (
          <p className="ops-copy-note">
            Only your team sees this note. {store.storefront_platform_allowed === false ? "The storefront is disabled by Tenali Platform. Contact the platform administrator. View " : "The storefront is turned off in "}
            <Link to="/portal/company#storefront-visibility">Company Setup</Link>.
          </p>
        ) : null}
      </section>
    </main>
  );
}

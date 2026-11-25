import { useAuth } from "../features/auth";
import type { Company } from "../types";
import { storefrontText } from "../features/catalog/storefrontText";
import { Link } from "react-router-dom";
import { storefrontLink } from "../features/catalog/storefrontLinks";

export function SiteFooter({ company }: { company?: Pick<Company, "company_name" | "nickname" | "email" | "storefront_content"> & Partial<Pick<Company, "storefront_template">> } = {}) {
  const {storefront,user}=useAuth();
  const store = company || storefront;
  const content=store?.storefront_content?.footer?.catalogue_label||"Product Catalogue";
  const footerText = store?.storefront_content?.footer?.contact_text ?? (store?.email || content);
  if (store?.storefront_template && store.storefront_template !== "current") {
    const text = (value: string) => storefrontText(value, store);
    const link = (key: string, href: string, label: string) => storefrontLink(store, `footer.${key}`, href, label);
    return <footer className={`marketplace-footer${store.storefront_template === "marketplace" ? "" : ` ${store.storefront_template}-footer`}`}>
      <div className="marketplace-footer-main">
        <div><strong>{store.company_name}</strong><p>{text(footerText)}</p></div>
        <nav aria-label="Discover"><h3>Discover</h3><Link {...link("categories", "/brand?category=all", "All categories")} /><Link {...link("best_sellers", "/#best-sellers", store.storefront_content?.navigation?.best_sellers || "Best sellers")} /><Link {...link("brands", "/brand?view=brands", store.storefront_content?.navigation?.brands || "Brands")} /></nav>
        <nav aria-label="Customer care"><h3>Customer care</h3><Link {...link("account", "/account", "Your account & orders")} /><Link {...link("contact", "/#contact", store.storefront_content?.navigation?.contact || "Contact support")} /><Link {...link("policies", "/policies/tenant", "Store policies")} /></nav>
        <nav aria-label="Our store"><h3>Our store</h3><Link {...link("about", "/#collection-special", "About us")} /><Link {...link("privacy", "/policies/tenant/privacy", "Privacy")} /><Link {...link("terms", "/policies/tenant/terms", "Terms & conditions")} /></nav>
      </div>
      <div className="marketplace-footer-bottom"><span>© {new Date().getFullYear()} {store.company_name}</span><span>Prices in INR</span></div>
    </footer>;
  }
  return (
    <footer>
      <strong>{store?.company_name||user?.company_name||'Tenali'}</strong>
      <span>{storefrontText(footerText, store || { company_name: user?.company_name || "Tenali" })}</span>
    </footer>
  );
}

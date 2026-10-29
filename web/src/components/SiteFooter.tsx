import { useAuth } from "../features/auth";

export function SiteFooter() {
  const {storefront,user}=useAuth();
  const content=storefront?.storefront_content?.footer?.catalogue_label||"Product Catalogue";
  return (
    <footer>
      <strong>{storefront?.company_name||user?.company_name||'Tenali'}</strong>
      <span>{storefront?.email||content}</span>
    </footer>
  );
}

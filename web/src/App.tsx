import { useEffect, useState, type SyntheticEvent } from "react";
import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { RequireWorkspace,StorefrontRoot,useAuth } from "./features/auth";
import { tenantApiOrigin, tenantBase } from "./features/tenantTransport";
import { useLocation } from "react-router-dom";
import { AccessPage } from "./pages/AccessPage";
import { TeamPage } from "./pages/TeamPage";
import { DomainsPage } from "./pages/DomainsPage";
import { AccountPage } from "./pages/AccountPage";
import { NewWorkspacePage } from "./pages/NewWorkspacePage";
import { AccountsPage } from "./pages/AccountsPage";
import { BrandPage } from "./pages/BrandPage";
import { BusinessPaymentsPage } from "./pages/BusinessPaymentsPage";
import { BillingPage } from "./pages/BillingPage";
import { CompanySetupPage } from "./pages/CompanySetupPage";
import { StorefrontDesignPage } from "./pages/StorefrontDesignPage";
import { CheckoutPage } from "./pages/CheckoutPage";
import { CartPage } from "./pages/CartPage";
import { CheckoutAdminPage } from "./pages/CheckoutAdminPage";
import { ShopperAccountPage } from "./pages/ShopperAccountPage";
import { PlatformAdminPage } from "./pages/PlatformAdminPage";
import { TenaliAIPage } from "./pages/TenaliAIPage";
import { MasterDataPage } from "./pages/MasterDataPage";
import { InventoryPage } from "./pages/InventoryPage";
import { BulkUploadPage } from "./pages/BulkUploadPage";
import { InventoryMasterPage } from "./pages/InventoryMasterPage";
import { AuditPage } from "./pages/AuditPage";
import { HomePage } from "./pages/HomePage";
import { PartiesPage } from "./pages/PartiesPage";
import { OnlineCustomersPage } from "./pages/OnlineCustomersPage";
import { PortalPage } from "./pages/PortalPage";
import { OperationsDashboardPage } from "./pages/OperationsDashboardPage";
import { ProductPage } from "./pages/ProductPage";
import { PurchasesPage } from "./pages/PurchasesPage";
import { ReceivablesPage } from "./pages/ReceivablesPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettlementsPage } from "./pages/SettlementsPage";
import { RefundSettlementsPage } from "./pages/RefundSettlementsPage";
import { StoresPage } from "./pages/StoresPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { TenantPoliciesPage } from "./pages/TenantPoliciesPage";
import { PolicyLinks } from "./components/PolicyLinks";
import { RouteScroll } from "./components/RouteScroll";
import { StorefrontGate } from "./components/StorefrontGate";
import type { Company, StorefrontSection } from "./types";

type StorefrontPreviewMessage = {
  type: "tenali-storefront-preview";
  companyId: string;
  company: Pick<Company, "storefront_template" | "site_theme" | "logo_url" | "storefront_content">;
  sections: StorefrontSection[];
};

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [previewDraft, setPreviewDraft] = useState<StorefrontPreviewMessage | null>(null);
  const auth = useAuth();
  const location = useLocation();
  const previewId = new URLSearchParams(location.search).get("storefrontPreview");
  useEffect(() => {
    setPreviewDraft(null);
    if (!previewId || !auth.user || auth.user.company_id !== previewId || auth.storefront?.id !== previewId) return;
    const receivePreview = (event: MessageEvent<unknown>) => {
      if (event.origin !== window.location.origin || event.source !== window.parent || !event.data || typeof event.data !== "object") return;
      const message = event.data as StorefrontPreviewMessage;
      if (message.type !== "tenali-storefront-preview" || message.companyId !== previewId ||
          !message.company || !Array.isArray(message.sections)) return;
      setPreviewDraft(message);
    };
    window.addEventListener("message", receivePreview);
    return () => window.removeEventListener("message", receivePreview);
  }, [previewId, auth.user?.company_id, auth.storefront?.id]);
  const platformHome = location.pathname === "/" && !tenantBase() && !tenantApiOrigin() && !auth.storefront;
  const workspaceFooter = location.pathname === "/portal" || location.pathname.startsWith("/portal/") ||
    location.pathname === "/login" || location.pathname === "/register";
  const storefrontTheme = !location.pathname.startsWith("/portal") && !location.pathname.startsWith("/platform")
    ? previewDraft?.company.storefront_template || auth.storefront?.storefront_template : undefined;
  const preventPreviewAction = previewId ? (event: SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
  } : undefined;

  return (
    <div className="app-root" data-storefront-template={storefrontTheme} data-storefront-preview={previewId ? "true" : undefined}
      onClickCapture={preventPreviewAction} onSubmitCapture={preventPreviewAction}
      onKeyDownCapture={event => {
        if (event.key === "Enter" || event.key === " ") preventPreviewAction?.(event);
      }}>
      <RouteScroll />
      {!platformHome && <Header menuOpen={menuOpen} onMenuToggle={() => setMenuOpen((prev) => !prev)} previewCompany={previewDraft?.company} />}
      <Routes>
        <Route path="/" element={<StorefrontRoot><StorefrontGate><HomePage /></StorefrontGate></StorefrontRoot>} />
        <Route path="/login" element={<AccessPage />} />
        <Route path="/register" element={<AccessPage register />} />
        <Route path="/account" element={<ShopperAccountPage />} />
        <Route path="/account/register" element={<ShopperAccountPage register />} />
        <Route path="/checkout" element={<StorefrontGate><CheckoutPage /></StorefrontGate>} />
        <Route path="/cart" element={<StorefrontGate><CartPage /></StorefrontGate>} />
        <Route path="/platform" element={<PlatformAdminPage />} />
        <Route path="/platform/authentication" element={<PlatformAdminPage />} />
        <Route path="/platform/policies" element={<PlatformAdminPage />} />
        <Route path="/platform/ai" element={<PlatformAdminPage />} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/policies/:scope" element={<PoliciesPage />} />
        <Route path="/policies/:scope/:kind" element={<PoliciesPage />} />
        <Route path="/brand" element={<StorefrontGate><BrandPage /></StorefrontGate>} />
        <Route path="/brand.html" element={<StorefrontGate><BrandPage /></StorefrontGate>} />
        <Route path="/products/:productId" element={<StorefrontGate><ProductPage /></StorefrontGate>} />
        <Route element={<RequireWorkspace />}>
        <Route path="/portal" element={<PortalPage />} />
        <Route path="/portal/ai" element={<TenaliAIPage />} />
        <Route path="/portal/dashboard" element={<OperationsDashboardPage />} />
        <Route path="/portal/parties" element={<PartiesPage />} />
        <Route path="/portal/online-customers" element={<OnlineCustomersPage />} />
        <Route path="/portal/accounts" element={<AccountsPage />} />
        <Route path="/portal/settlements" element={<SettlementsPage />} />
        <Route path="/portal/settlements/refunds" element={<RefundSettlementsPage />} />
        <Route path="/portal/business-payments" element={<BusinessPaymentsPage />} />
        <Route path="/portal/receivables" element={<ReceivablesPage />} />
        <Route path="/portal/purchases" element={<PurchasesPage />} />
        <Route path="/portal/billing" element={<BillingPage />} />
        <Route path="/portal/company" element={<CompanySetupPage />} />
        <Route path="/portal/storefront-design" element={<StorefrontDesignPage />} />
        <Route path="/portal/policies" element={<TenantPoliciesPage />} />
        <Route path="/portal/stores" element={<StoresPage />} />
        <Route path="/portal/checkout" element={<CheckoutAdminPage key="orders" />} />
        <Route path="/portal/checkout-setup" element={<CheckoutAdminPage key="setup" setupOnly />} />
        <Route path="/portal/masters" element={<MasterDataPage />} />
        <Route path="/portal/inventory" element={<InventoryPage />} />
        <Route path="/portal/bulk-upload" element={<BulkUploadPage />} />
        <Route path="/portal/masters/hsn" element={<MasterDataPage />} />
        <Route path="/portal/masters/brands" element={<InventoryMasterPage key="brands" kind="brands" />} />
        <Route path="/portal/masters/categories" element={<InventoryMasterPage key="categories" kind="categories" />} />
        <Route path="/portal/reports" element={<ReportsPage />} />
        <Route path="/portal/audit" element={<AuditPage />} />
        <Route path="/portal/team" element={<TeamPage/>}/>
        <Route path="/portal/account" element={<AccountPage/>}/>
        <Route path="/portal/new-workspace" element={<NewWorkspacePage/>}/>
        <Route path="/portal/domains" element={<DomainsPage/>}/>
        </Route>
      </Routes>
      {!platformHome && <div className={`policy-footer${workspaceFooter ? " policy-footer-workspace" : ""}`}><PolicyLinks /></div>}
    </div>
  );
}
